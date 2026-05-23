"""Related-post detection — M5.3–M5.7。

四類後續事件偵測：

    author_followup  作者後續貼文     scraper.fetch_user_submissions(author, limit=20)
    author_reply     原作者本人留言     scraper.fetch_comment_tree → is_submitter=True
    hot_reply        高熱度留言       comment.score 突出（≥50 或 ≥ 1.3×第二名）
    crosspost        被轉貼到別 sub   scraper.fetch_duplicates(post_id)

偵測函式為純函式（接收已抓好的資料、不打網路），方便用 FakeScraper / 直接餵
fixture 做 unit test。`detect_for_tracked` 編排：

    1. 依需要打 scraper 各 endpoint（每類獨立 try/except，單類失敗不阻塞其他）
    2. 跑各 detect_* 取得 RelatedFinding 串列
    3. evaluate_milestone 標 is_milestone
    4. persist_findings 寫 RelatedPost row，dedup 鍵
       = (tracked_post_id, relation_type, reddit_post_id)
       — alembic 上的 UniqueConstraint `uq_related_post_triple` 保險，
         insert 前先 SELECT 過濾省去 INSERT 失敗回滾

M5.7 milestone 判定先採啟發式 + 閾值（reddit_tracker_proposal §4.5 提到的條件）。
日後可換成 Haiku 對 finding.content 做語義判斷（事件是否質變 / 解結），介面
`evaluate_milestone` 收 finding 已預留擴充點。
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import RelatedPost, TrackedPost
from ..scrapers.base import CommentNode, PostPayload, RedditScraper

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 常數
# ---------------------------------------------------------------------------

RELATION_AUTHOR_FOLLOWUP = "author_followup"
RELATION_AUTHOR_REPLY = "author_reply"
RELATION_HOT_REPLY = "hot_reply"
RELATION_CROSSPOST = "crosspost"

ALL_RELATIONS = (
    RELATION_AUTHOR_FOLLOWUP,
    RELATION_AUTHOR_REPLY,
    RELATION_HOT_REPLY,
    RELATION_CROSSPOST,
)

# Milestone 閾值。`relevance_score` 因類別語意不同：
#   author_followup → 標題二元組 Jaccard (+ 同 sub 加成)，範圍 0–1
#   author_reply / hot_reply → 留言 net score（raw 整數，存 float column）
#   crosspost → crosspost.score（raw 整數）
MILESTONE_THRESHOLDS = {
    RELATION_AUTHOR_FOLLOWUP: 0.7,
    RELATION_AUTHOR_REPLY: 20.0,
    RELATION_HOT_REPLY: 200.0,
    RELATION_CROSSPOST: 100.0,
}

# Hot reply 判定門檻
HOT_REPLY_ABS_SCORE = 50
HOT_REPLY_RELATIVE_MARGIN = 1.3   # 比第二名高 30%+

# author_followup：只看原貼之後 N 天內的後續貼文
FOLLOWUP_WINDOW_DAYS = 30
FOLLOWUP_SAME_SUB_BONUS = 0.3

# Detection 上限
COMMENT_FETCH_LIMIT = 200


# ---------------------------------------------------------------------------
# 資料結構
# ---------------------------------------------------------------------------


@dataclass
class RelatedFinding:
    relation_type: str
    reddit_post_id: str | None       # post id 或 comment id（皆 7 字以內，fit String(16)）
    posted_at: datetime | None
    content: str                      # 人類可讀摘要
    relevance_score: float | None
    is_milestone: bool = False


@dataclass
class DetectionStat:
    fetched: dict[str, int] = field(default_factory=dict)   # 'submissions' / 'comments' / 'dups'
    findings_by_type: dict[str, int] = field(default_factory=dict)
    inserted: int = 0
    skipped_dupe: int = 0
    milestones: int = 0
    errors: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# helpers — 純函式
# ---------------------------------------------------------------------------


def _ensure_utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def _normalize(text: str | None) -> str:
    """小寫 + 移除空白。給 _bigrams 用。"""
    if not text:
        return ""
    return re.sub(r"\s+", "", text.lower())


def _bigrams(text: str) -> set[str]:
    """字元二元組。同時對 CJK 與英文工作得不錯（不依賴空白切詞）。"""
    s = _normalize(text)
    if len(s) < 2:
        return {s} if s else set()
    return {s[i : i + 2] for i in range(len(s) - 1)}


def _jaccard(a: str, b: str) -> float:
    ga, gb = _bigrams(a), _bigrams(b)
    if not ga or not gb:
        return 0.0
    return len(ga & gb) / len(ga | gb)


def title_similarity(orig_title: str, orig_sub: str, new_title: str, new_sub: str) -> float:
    """0–1 的相關性分數：標題二元組 Jaccard + 同 sub 加成（capped at 1）。"""
    score = _jaccard(orig_title, new_title)
    if orig_sub and new_sub and orig_sub.lower() == new_sub.lower():
        score = min(1.0, score + FOLLOWUP_SAME_SUB_BONUS)
    return score


def evaluate_milestone(finding: RelatedFinding) -> bool:
    """依 relation_type 與閾值判定 finding 是否為 milestone（M5.7 baseline）。

    TODO M5.7+：可換成 Haiku 對 finding.content 做語義判斷（事件是否質變 /
    解結）。介面已預留 — 屆時把這個函式 swap 出去即可，不影響呼叫端。
    """
    th = MILESTONE_THRESHOLDS.get(finding.relation_type)
    if th is None or finding.relevance_score is None:
        return False
    return finding.relevance_score >= th


# ---------------------------------------------------------------------------
# detect_* — 四類偵測（純函式，接已抓好的資料）
# ---------------------------------------------------------------------------


def detect_author_followup(
    tracked: TrackedPost,
    submissions: list[PostPayload],
    *,
    now: datetime | None = None,
    window_days: int = FOLLOWUP_WINDOW_DAYS,
) -> list[RelatedFinding]:
    """5.3：作者近期貼文中，比原貼新且非自己的，皆為候選。"""
    now = _ensure_utc(now) or datetime.now(timezone.utc)
    cand = tracked.candidate
    if cand is None or not submissions:
        return []
    orig_posted = _ensure_utc(cand.posted_at or cand.discovered_at)
    if orig_posted is None:
        return []
    earliest = orig_posted
    latest = now

    findings: list[RelatedFinding] = []
    for p in submissions:
        if p.reddit_post_id == cand.reddit_post_id:
            continue
        posted_at = _ensure_utc(p.created_utc)
        if posted_at is None or posted_at <= earliest or posted_at > latest:
            continue
        relevance = title_similarity(
            cand.title or "", cand.subreddit, p.title, p.subreddit
        )
        findings.append(
            RelatedFinding(
                relation_type=RELATION_AUTHOR_FOLLOWUP,
                reddit_post_id=p.reddit_post_id,
                posted_at=posted_at,
                content=f"[r/{p.subreddit}] {p.title}",
                relevance_score=relevance,
            )
        )
    return findings


def detect_author_reply(
    tracked: TrackedPost,
    comments: list[CommentNode],
) -> list[RelatedFinding]:
    """5.4：comment.author == submission.author（CommentNode.is_submitter）。"""
    findings: list[RelatedFinding] = []
    for node in comments:
        if node.is_more_placeholder:
            continue
        if not node.is_submitter:
            continue
        body_snippet = (node.body or "").strip().replace("\n", " ")[:200]
        findings.append(
            RelatedFinding(
                relation_type=RELATION_AUTHOR_REPLY,
                reddit_post_id=node.comment_id or None,
                posted_at=_ensure_utc(node.created_utc),
                content=f"[OP reply, score={node.score}] {body_snippet}",
                relevance_score=float(node.score),
            )
        )
    return findings


def detect_hot_reply(
    tracked: TrackedPost,
    comments: list[CommentNode],
    *,
    abs_threshold: int = HOT_REPLY_ABS_SCORE,
    relative_margin: float = HOT_REPLY_RELATIVE_MARGIN,
) -> list[RelatedFinding]:
    """5.5：comment.score 突出（絕對 ≥ abs_threshold，或 ≥ relative_margin × 第二名）。

    純函式；同 commentNode 不會 fire 兩次（即使是 OP 也可能同時是 hot_reply）—
    這層只負責找；persist 階段以 (relation_type, comment_id) 去重，OP reply 與
    hot reply 視為不同 relation，會各寫一筆（這也呼應「OP 的高熱度留言尤其重要」
    這個直覺）。
    """
    candidates = [n for n in comments if not n.is_more_placeholder and n.score > 0]
    if not candidates:
        return []
    sorted_desc = sorted(candidates, key=lambda n: n.score, reverse=True)
    second_top = sorted_desc[1].score if len(sorted_desc) >= 2 else 0

    findings: list[RelatedFinding] = []
    for node in sorted_desc:
        passes_abs = node.score >= abs_threshold
        passes_rel = (
            second_top > 0
            and len(sorted_desc) >= 2
            and node is sorted_desc[0]
            and node.score >= second_top * relative_margin
        )
        if not (passes_abs or passes_rel):
            continue
        body_snippet = (node.body or "").strip().replace("\n", " ")[:200]
        findings.append(
            RelatedFinding(
                relation_type=RELATION_HOT_REPLY,
                reddit_post_id=node.comment_id or None,
                posted_at=_ensure_utc(node.created_utc),
                content=f"[hot reply, score={node.score}] {body_snippet}",
                relevance_score=float(node.score),
            )
        )
    return findings


def detect_crossposts(
    tracked: TrackedPost,
    duplicates: list[PostPayload],
) -> list[RelatedFinding]:
    """5.6：fetch_duplicates 的 PostPayload 串列直接收。"""
    cand = tracked.candidate
    findings: list[RelatedFinding] = []
    for p in duplicates:
        if cand is not None and p.reddit_post_id == cand.reddit_post_id:
            continue
        findings.append(
            RelatedFinding(
                relation_type=RELATION_CROSSPOST,
                reddit_post_id=p.reddit_post_id,
                posted_at=_ensure_utc(p.created_utc),
                content=f"[crosspost r/{p.subreddit} score={p.score}] {p.title}",
                relevance_score=float(p.score),
            )
        )
    return findings


# ---------------------------------------------------------------------------
# 編排 — 對單一 tracked 跑四類偵測 + 持久化
# ---------------------------------------------------------------------------


def persist_findings(
    session: Session,
    tracked_post_id: int,
    findings: list[RelatedFinding],
    *,
    now: datetime | None = None,
) -> tuple[int, int, int]:
    """寫 RelatedPost rows，回 (inserted, skipped_dupe, milestones)。

    dedup 鍵 = (tracked_post_id, relation_type, reddit_post_id)；同批內也防重。
    """
    if not findings:
        return (0, 0, 0)
    now = _ensure_utc(now) or datetime.now(timezone.utc)

    existing = set(
        session.execute(
            select(RelatedPost.relation_type, RelatedPost.reddit_post_id).where(
                RelatedPost.tracked_post_id == tracked_post_id
            )
        ).all()
    )

    inserted = 0
    dupe = 0
    milestones = 0
    seen: set[tuple[str, str | None]] = set()
    for f in findings:
        key = (f.relation_type, f.reddit_post_id)
        if key in existing or key in seen:
            dupe += 1
            continue
        is_ms = evaluate_milestone(f)
        if is_ms:
            milestones += 1
        session.add(
            RelatedPost(
                tracked_post_id=tracked_post_id,
                reddit_post_id=f.reddit_post_id,
                relation_type=f.relation_type,
                relevance_score=f.relevance_score,
                is_milestone=is_ms,
                content=f.content,
                posted_at=f.posted_at,
            )
        )
        seen.add(key)
        inserted += 1
    session.flush()
    return (inserted, dupe, milestones)


def detect_for_tracked(
    session: Session,
    scraper: RedditScraper,
    tracked: TrackedPost,
    *,
    now: datetime | None = None,
    comment_limit: int = COMMENT_FETCH_LIMIT,
    submissions_limit: int = 20,
) -> DetectionStat:
    """對單一 TrackedPost 跑四類偵測，寫 RelatedPost row。"""
    stat = DetectionStat()
    cand = tracked.candidate
    if cand is None:
        stat.errors.append("candidate_missing")
        return stat

    all_findings: list[RelatedFinding] = []

    # --- author_followup ---
    if cand.author_username:
        try:
            subs = scraper.fetch_user_submissions(
                cand.author_username, limit=submissions_limit
            )
            stat.fetched["submissions"] = len(subs)
            f = detect_author_followup(tracked, subs, now=now)
            stat.findings_by_type[RELATION_AUTHOR_FOLLOWUP] = len(f)
            all_findings.extend(f)
        except Exception as e:  # noqa: BLE001
            logger.warning(
                "fetch_user_submissions(%s) failed: %s", cand.author_username, e
            )
            stat.errors.append(f"author_followup:{e}")

    # --- author_reply + hot_reply 共用一次 fetch_comment_tree ---
    try:
        comments = scraper.fetch_comment_tree(
            cand.reddit_post_id, limit=comment_limit
        )
        stat.fetched["comments"] = len(comments)
        f_reply = detect_author_reply(tracked, comments)
        f_hot = detect_hot_reply(tracked, comments)
        stat.findings_by_type[RELATION_AUTHOR_REPLY] = len(f_reply)
        stat.findings_by_type[RELATION_HOT_REPLY] = len(f_hot)
        all_findings.extend(f_reply)
        all_findings.extend(f_hot)
    except Exception as e:  # noqa: BLE001
        logger.warning("fetch_comment_tree(%s) failed: %s", cand.reddit_post_id, e)
        stat.errors.append(f"comment_tree:{e}")

    # --- crosspost ---
    try:
        dups = scraper.fetch_duplicates(cand.reddit_post_id)
        stat.fetched["duplicates"] = len(dups)
        f = detect_crossposts(tracked, dups)
        stat.findings_by_type[RELATION_CROSSPOST] = len(f)
        all_findings.extend(f)
    except Exception as e:  # noqa: BLE001
        logger.warning("fetch_duplicates(%s) failed: %s", cand.reddit_post_id, e)
        stat.errors.append(f"duplicates:{e}")

    inserted, dupe, ms = persist_findings(session, tracked.id, all_findings, now=now)
    stat.inserted = inserted
    stat.skipped_dupe = dupe
    stat.milestones = ms

    logger.info(
        "detection tracked=%d post=%s: fetched=%s inserted=%d dupe=%d milestones=%d errors=%d",
        tracked.id, cand.reddit_post_id,
        stat.fetched, stat.inserted, stat.skipped_dupe, stat.milestones,
        len(stat.errors),
    )
    return stat


__all__ = [
    "ALL_RELATIONS",
    "DetectionStat",
    "HOT_REPLY_ABS_SCORE",
    "HOT_REPLY_RELATIVE_MARGIN",
    "MILESTONE_THRESHOLDS",
    "RELATION_AUTHOR_FOLLOWUP",
    "RELATION_AUTHOR_REPLY",
    "RELATION_CROSSPOST",
    "RELATION_HOT_REPLY",
    "RelatedFinding",
    "detect_author_followup",
    "detect_author_reply",
    "detect_crossposts",
    "detect_for_tracked",
    "detect_hot_reply",
    "evaluate_milestone",
    "persist_findings",
    "title_similarity",
]

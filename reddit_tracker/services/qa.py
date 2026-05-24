"""QA session 層 — M6 問答層。

每使用者最多一個 active session：
- `open_session`：建 `qa_sessions` row（state='active'）+ in-memory state；
  system prompt 在這時組好 cache 在記憶體（之後每輪沿用）。
- `handle_message`：以同樣 system prompt + 累積的 history 呼叫 ChatClient；
  寫 user/assistant 兩筆 `qa_messages` + 一筆 `llm_records`。
- `close_session`：寫 `qa_sessions.ended_at` + `state`；移除 in-memory state。
- `sweep_idle`：scheduler 用，掃 in-memory state 找超過 IDLE_TTL 沒互動的
  session 關掉，回收 user_id list。

In-memory state 用 module-level dict + threading.Lock 保護（bot handler 在
asyncio thread 跑、scheduler sweep 在 BlockingScheduler thread 跑）。

Context 組裝原則（reddit_tracker_proposal §4.6）：
1. 原貼基本資料 + 最新 snapshot（演化）
2. 完整 comment tree（縮排呈現）
3. 作者後續貼文（用 related_posts 內已偵測的 author_followup）
4. 其他 related events（hot_reply / crosspost / author_reply）

Token 預算：comment_tree.estimate_tokens 粗估，> 18k 就先 trim comment
list（top-N by score）；M7 token baseline 會以此調整。
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..llm.minimax_chat import ChatClient, ChatResult
from ..models import (
    CandidatePost,
    LLMRecord,
    PostSnapshot,
    QAMessage,
    QASession,
    RelatedPost,
    TrackedPost,
)
from ..scrapers.base import CommentNode, RedditScraper
from .comment_tree import estimate_tokens, to_prompt_text, top_n_by_score
from .detection import (
    RELATION_AUTHOR_FOLLOWUP,
    RELATION_AUTHOR_REPLY,
    RELATION_CROSSPOST,
    RELATION_HOT_REPLY,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 常數
# ---------------------------------------------------------------------------

IDLE_TTL_SECONDS = 5 * 60          # 5 分鐘無互動 → idle timeout
STATE_ACTIVE = "active"
STATE_ENDED_MANUAL = "ended"
STATE_ENDED_IDLE = "ended_idle"

# 重量 context 上限（粗估 token）；超出就 trim comment tree 至 top-N by score
CONTEXT_TOKEN_BUDGET = 18000
COMMENT_TRIM_TOP_N = 60
DEFAULT_COMMENT_TREE_LIMIT = 500

SYSTEM_PROMPT_HEADER = """你是一個 Reddit 素人爆文追蹤助手。
使用者已收藏一篇貼文，會就這篇貼文做多輪提問。

回答原則：
1. 嚴格只依據下方 context（原貼 / 留言樹 / 追蹤事件）作答；不要編造事實
2. 若 context 沒提到某資訊，明說「目前資料沒有提到」，不要猜
3. 引用留言時可加上 (u/<author>, score=N) 標註以利溯源
4. 中英文都吃，使用者用什麼語言就用什麼語言回
5. 簡潔（除非使用者明確要求展開）
"""


# ---------------------------------------------------------------------------
# 資料結構
# ---------------------------------------------------------------------------


@dataclass
class QASessionState:
    """In-memory active session state。"""

    user_id: int
    tracked_post_id: int
    qa_session_id: int
    system_prompt: str
    history: list[dict] = field(default_factory=list)   # [{role,content}, ...]
    system_tokens_estimate: int = 0
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    last_active_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


# user_id → state
_ACTIVE: dict[int, QASessionState] = {}
_LOCK = threading.Lock()


# ---------------------------------------------------------------------------
# in-memory state helpers（thread-safe）
# ---------------------------------------------------------------------------


def get_active(user_id: int) -> QASessionState | None:
    with _LOCK:
        return _ACTIVE.get(user_id)


def _set_active(state: QASessionState) -> None:
    with _LOCK:
        _ACTIVE[state.user_id] = state


def _pop_active(user_id: int) -> QASessionState | None:
    with _LOCK:
        return _ACTIVE.pop(user_id, None)


def reset_state() -> None:
    """測試用：清空 in-memory state。"""
    with _LOCK:
        _ACTIVE.clear()


# ---------------------------------------------------------------------------
# context 組裝
# ---------------------------------------------------------------------------


def _fmt_dt(dt: datetime | None) -> str:
    if dt is None:
        return "(unknown)"
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.strftime("%Y-%m-%d %H:%M UTC")


def _build_post_section(cand: CandidatePost) -> str:
    karma = cand.author_karma if cand.author_karma is not None else "unknown"
    ratio = (
        f"{cand.upvote_ratio:.2f}" if cand.upvote_ratio is not None else "unknown"
    )
    body = (cand.selftext or "(no selftext / link post)").strip()
    return (
        f"[ORIGINAL POST]\n"
        f"r/{cand.subreddit} · u/{cand.author_username or '[deleted]'} "
        f"(karma={karma})\n"
        f"Posted: {_fmt_dt(cand.posted_at)}\n"
        f"Initial: score={cand.initial_score} comments={cand.initial_num_comments}"
        f" upvote_ratio={ratio}\n"
        f"\n"
        f"Title: {cand.title or ''}\n"
        f"\n"
        f"Body:\n{body}"
    )


def _build_snapshots_section(snaps: list[PostSnapshot]) -> str:
    if not snaps:
        return "[SNAPSHOTS]\n(無快照記錄 — 可能剛收藏不久)"
    lines = [f"[SNAPSHOTS] 共 {len(snaps)} 筆，最舊→最新"]
    for s in snaps:
        ratio = (
            f"{s.upvote_ratio:.2f}" if s.upvote_ratio is not None else "?"
        )
        lines.append(
            f"  {_fmt_dt(s.captured_at)} · score={s.score or 0} "
            f"comments={s.num_comments or 0} ↑{ratio}"
        )
    return "\n".join(lines)


def _build_related_section(rels: list[RelatedPost]) -> str:
    if not rels:
        return "[RELATED EVENTS]\n(尚無偵測到的後續事件)"
    by_type: dict[str, list[RelatedPost]] = {}
    for r in rels:
        by_type.setdefault(r.relation_type, []).append(r)

    order = [
        (RELATION_AUTHOR_FOLLOWUP, "作者後續貼文"),
        (RELATION_AUTHOR_REPLY, "作者本人留言"),
        (RELATION_HOT_REPLY, "高熱度留言"),
        (RELATION_CROSSPOST, "跨 sub 轉貼"),
    ]
    lines = ["[RELATED EVENTS]"]
    for relation, label in order:
        items = by_type.get(relation, [])
        if not items:
            continue
        lines.append(f"  {label} ({len(items)} 筆)：")
        items.sort(
            key=lambda r: (r.relevance_score or 0.0, r.posted_at or datetime.min),
            reverse=True,
        )
        for r in items[:8]:
            star = "★" if r.is_milestone else " "
            content = (r.content or "")[:200]
            lines.append(
                f"   {star} {_fmt_dt(r.posted_at or r.discovered_at)}"
                f" · score={r.relevance_score} · {content}"
            )
    return "\n".join(lines)


def _build_comments_section(comments: list[CommentNode]) -> str:
    if not comments:
        return "[COMMENT TREE]\n(無留言)"
    return f"[COMMENT TREE] 共 {len(comments)} 節點\n{to_prompt_text(comments)}"


def _fetch_tracked_context_data(
    db: Session, tracked_post_id: int
) -> tuple[TrackedPost, CandidatePost, list[PostSnapshot], list[RelatedPost]]:
    """從 DB 撈組 context 用的 ORM 資料。Raise 若 tracked 不存在。"""
    tracked = db.get(TrackedPost, tracked_post_id)
    if tracked is None:
        raise LookupError(f"tracked_post id={tracked_post_id} not found")
    cand = db.get(CandidatePost, tracked.candidate_post_id)
    if cand is None:
        raise LookupError(
            f"candidate id={tracked.candidate_post_id} 對應的 tracked={tracked_post_id} 不見了"
        )
    snaps = list(
        db.scalars(
            select(PostSnapshot)
            .where(PostSnapshot.tracked_post_id == tracked_post_id)
            .order_by(PostSnapshot.captured_at.asc())
        ).all()
    )
    rels = list(
        db.scalars(
            select(RelatedPost).where(RelatedPost.tracked_post_id == tracked_post_id)
        ).all()
    )
    return tracked, cand, snaps, rels


def build_system_prompt(
    db: Session,
    tracked_post_id: int,
    *,
    scraper: RedditScraper | None = None,
    comment_limit: int = DEFAULT_COMMENT_TREE_LIMIT,
    token_budget: int = CONTEXT_TOKEN_BUDGET,
) -> tuple[str, int]:
    """組重量 system prompt。回 (prompt_text, comment_node_count)。

    `scraper` 為 None 時 comment tree 留空（測試 / 沒網路時的 fallback）。
    超過 token_budget 會把 comment list trim 到 top-N by score 後重組。
    """
    _, cand, snaps, rels = _fetch_tracked_context_data(db, tracked_post_id)

    sections: list[str] = [
        SYSTEM_PROMPT_HEADER,
        _build_post_section(cand),
        _build_snapshots_section(snaps),
        _build_related_section(rels),
    ]

    comments: list[CommentNode] = []
    if scraper is not None:
        try:
            comments = scraper.fetch_comment_tree(
                cand.reddit_post_id, limit=comment_limit
            )
        except Exception as e:  # noqa: BLE001 — context 取不到不阻塞
            logger.warning(
                "build_system_prompt: fetch_comment_tree(%s) failed: %s",
                cand.reddit_post_id, e,
            )
            comments = []

    sections.append(_build_comments_section(comments))
    prompt = "\n\n".join(sections)

    # token budget — 若超出，把 comments trim 到 top-N by score 後重組
    if comments and estimate_tokens(prompt) > token_budget:
        trimmed = top_n_by_score(comments, n=COMMENT_TRIM_TOP_N)
        sections[-1] = (
            f"[COMMENT TREE — trimmed to top {len(trimmed)} by score / "
            f"original {len(comments)}]\n{to_prompt_text(trimmed)}"
        )
        prompt = "\n\n".join(sections)
        comments_kept = len(trimmed)
    else:
        comments_kept = len(comments)

    return prompt, comments_kept


# ---------------------------------------------------------------------------
# session lifecycle
# ---------------------------------------------------------------------------


@dataclass
class OpenOutcome:
    state: QASessionState | None
    already_active: bool = False
    not_owner: bool = False
    not_found: bool = False
    archived: bool = False


def open_session(
    db: Session,
    *,
    user_id: int,
    tracked_post_id: int,
    scraper: RedditScraper | None = None,
    now: datetime | None = None,
) -> OpenOutcome:
    """打開一個 QA session。caller commit。

    Pre-conditions：
      - 該 user 沒有 active session
      - tracked_post 存在、屬於該 user、且 status='active'

    回 OpenOutcome：state 有值表示成功；其餘旗標說明拒絕原因。
    """
    now = now or datetime.now(timezone.utc)
    existing = get_active(user_id)
    if existing is not None:
        return OpenOutcome(state=existing, already_active=True)

    tracked = db.get(TrackedPost, tracked_post_id)
    if tracked is None:
        return OpenOutcome(state=None, not_found=True)
    if tracked.user_id != user_id:
        return OpenOutcome(state=None, not_owner=True)
    if tracked.status != "active":
        return OpenOutcome(state=None, archived=True)

    prompt, comments_kept = build_system_prompt(
        db, tracked_post_id, scraper=scraper
    )

    row = QASession(
        user_id=user_id,
        tracked_post_id=tracked_post_id,
        state=STATE_ACTIVE,
    )
    db.add(row)
    db.flush()

    state = QASessionState(
        user_id=user_id,
        tracked_post_id=tracked_post_id,
        qa_session_id=row.id,
        system_prompt=prompt,
        system_tokens_estimate=estimate_tokens(prompt),
        started_at=now,
        last_active_at=now,
    )
    _set_active(state)
    logger.info(
        "qa.open user=%d tracked=%d session=%d system_tokens~%d comments=%d",
        user_id, tracked_post_id, row.id,
        state.system_tokens_estimate, comments_kept,
    )
    return OpenOutcome(state=state)


@dataclass
class TurnOutcome:
    reply: str | None
    cost_usd: float | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    error: str | None = None
    not_in_session: bool = False


def handle_message(
    db: Session,
    *,
    user_id: int,
    text: str,
    chat: ChatClient,
    now: datetime | None = None,
) -> TurnOutcome:
    """處理 active session 的下一輪訊息。caller commit。

    寫 user QAMessage → 呼叫 chat.complete → 寫 assistant QAMessage + LLMRecord。
    Chat 失敗時不寫 assistant row；user row 仍寫入（追蹤已嘗試對話）。
    """
    now = now or datetime.now(timezone.utc)
    state = get_active(user_id)
    if state is None:
        return TurnOutcome(reply=None, not_in_session=True)

    user_msg = QAMessage(
        qa_session_id=state.qa_session_id,
        role="user",
        content=text,
    )
    db.add(user_msg)
    db.flush()
    state.history.append({"role": "user", "content": text})

    try:
        result: ChatResult = chat.complete(
            system=state.system_prompt,
            messages=list(state.history),
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("qa.chat failed user=%d session=%d: %s", user_id, state.qa_session_id, e)
        # rollback in-memory history 以免下次重送
        state.history.pop()
        return TurnOutcome(reply=None, error=str(e))

    state.history.append({"role": "assistant", "content": result.content})
    state.last_active_at = now

    cost_dec = (
        Decimal(str(result.cost_usd)) if result.cost_usd is not None else None
    )
    db.add(
        QAMessage(
            qa_session_id=state.qa_session_id,
            role="assistant",
            content=result.content,
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
            cost_usd=cost_dec,
        )
    )
    db.add(
        LLMRecord(
            provider=chat.provider,
            model=chat.model,
            purpose="qa",
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
            cached_tokens=result.cached_tokens,
            cost_usd=cost_dec,
            context_ref={
                "qa_session_id": state.qa_session_id,
                "tracked_post_id": state.tracked_post_id,
                "turn": len(state.history) // 2,
            },
        )
    )
    db.flush()

    logger.info(
        "qa.turn user=%d session=%d turn=%d in=%s out=%s cost=%s",
        user_id, state.qa_session_id, len(state.history) // 2,
        result.input_tokens, result.output_tokens, result.cost_usd,
    )
    return TurnOutcome(
        reply=result.content,
        cost_usd=result.cost_usd,
        input_tokens=result.input_tokens,
        output_tokens=result.output_tokens,
    )


@dataclass
class CloseOutcome:
    closed: bool
    reason: str | None = None
    qa_session_id: int | None = None
    turns: int = 0
    not_in_session: bool = False


def close_session(
    db: Session,
    *,
    user_id: int,
    reason: str = STATE_ENDED_MANUAL,
    now: datetime | None = None,
) -> CloseOutcome:
    """關閉 active session。caller commit。"""
    now = now or datetime.now(timezone.utc)
    state = _pop_active(user_id)
    if state is None:
        return CloseOutcome(closed=False, not_in_session=True)
    row = db.get(QASession, state.qa_session_id)
    if row is not None:
        row.state = reason
        row.ended_at = now
    db.flush()
    logger.info(
        "qa.close user=%d session=%d reason=%s turns=%d",
        user_id, state.qa_session_id, reason, len(state.history) // 2,
    )
    return CloseOutcome(
        closed=True,
        reason=reason,
        qa_session_id=state.qa_session_id,
        turns=len(state.history) // 2,
    )


def sweep_idle(
    db: Session,
    *,
    ttl_seconds: int = IDLE_TTL_SECONDS,
    now: datetime | None = None,
) -> list[int]:
    """掃 in-memory state，關掉超過 ttl_seconds 無互動的 session。

    回被關掉的 user_id list。caller commit。
    """
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(seconds=ttl_seconds)
    with _LOCK:
        stale_users = [
            uid for uid, st in _ACTIVE.items() if st.last_active_at <= cutoff
        ]
    closed: list[int] = []
    for uid in stale_users:
        outcome = close_session(
            db, user_id=uid, reason=STATE_ENDED_IDLE, now=now
        )
        if outcome.closed:
            closed.append(uid)
    if closed:
        logger.info("qa.sweep_idle closed=%d users=%s", len(closed), closed)
    return closed


__all__ = [
    "CONTEXT_TOKEN_BUDGET",
    "CloseOutcome",
    "IDLE_TTL_SECONDS",
    "OpenOutcome",
    "QASessionState",
    "STATE_ACTIVE",
    "STATE_ENDED_IDLE",
    "STATE_ENDED_MANUAL",
    "SYSTEM_PROMPT_HEADER",
    "TurnOutcome",
    "build_system_prompt",
    "close_session",
    "get_active",
    "handle_message",
    "open_session",
    "reset_state",
    "sweep_idle",
]

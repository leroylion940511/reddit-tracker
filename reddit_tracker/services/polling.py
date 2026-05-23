"""Tiered polling — M5.2。

Tracked post 的快照輪詢，沿用 v3 的 age-tier 演算法：

    age 0–24h  → tier='hot'      / 每 15 分鐘
    age 1–7d   → tier='cooling'  / 每 60 分鐘
    age 7–30d  → tier='archive'  / 每 6 小時
    age >30d   → status='archived'，不再輪詢

注意 polling_tier='archive' ≠ status='archived'：

  - polling_tier='archive' 仍在追蹤，只是輪詢頻率降到 6h 一次
  - status='archived' 是「終止追蹤」，貼文壽命已過 30 天或被刪除/隔離

每輪 select_due_posts → capture_snapshot：

  - 打 `scraper.fetch_post(reddit_post_id)` 拿目前 score / num_comments / upvote_ratio
  - 寫一筆 `post_snapshots` row（new_comments 留 None，M5.3+ 才會帶入）
  - 視 age 升降 tier；過 30d 直接 archived

留言層級的偵測（hot_reply / author_reply / crosspost / author_followup）由 M5.3–
M5.6 接手；本層只負責 post-level 快照，把基礎打穩。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import CandidatePost, PostSnapshot, TrackedPost
from ..scrapers.base import RedditScraper

logger = logging.getLogger(__name__)


# Tier 名稱
TIER_HOT = "hot"
TIER_COOLING = "cooling"
TIER_ARCHIVE = "archive"

# (tier, age_upper_bound_hours, interval_minutes)
TIER_RULES: list[tuple[str, float, int]] = [
    (TIER_HOT, 24.0, 15),
    (TIER_COOLING, 24.0 * 7, 60),
    (TIER_ARCHIVE, 24.0 * 30, 360),
]

# TrackedPost.status 常數
ACTIVE_STATUS = "active"
ARCHIVED_STATUS = "archived"


# ---------------------------------------------------------------------------
# pure functions（無 DB / scraper 依賴，方便邊界值測試）
# ---------------------------------------------------------------------------


def tier_for_age(age_hours: float) -> str | None:
    """根據 age 決定 polling_tier；> 30 天回 None（caller 應將 status 改 archived）。

    邊界包含上界：age=24h → 'hot'、age=168h → 'cooling'。
    """
    for tier, upper, _ in TIER_RULES:
        if age_hours <= upper:
            return tier
    return None


def interval_minutes_for_tier(tier: str) -> int | None:
    for t, _, mins in TIER_RULES:
        if t == tier:
            return mins
    return None


def _ensure_utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def _age_hours(post: CandidatePost, now: datetime) -> float:
    ref = _ensure_utc(post.posted_at or post.discovered_at)
    if ref is None:
        return 0.0
    delta = (now - ref).total_seconds() / 3600.0
    return max(delta, 0.0)


# ---------------------------------------------------------------------------
# 結果型別
# ---------------------------------------------------------------------------


@dataclass
class SnapshotResult:
    tracked_post_id: int
    captured: bool
    archived: bool = False
    tier_changed: tuple[str, str] | None = None    # (old, new) 若有變
    error: str | None = None


@dataclass
class PollingStat:
    total_due: int = 0
    captured: int = 0
    archived: int = 0
    errors: int = 0
    snapshots: list[SnapshotResult] = field(default_factory=list)


# ---------------------------------------------------------------------------
# 排程入口
# ---------------------------------------------------------------------------


def select_due_posts(
    session: Session,
    *,
    now: datetime | None = None,
) -> list[TrackedPost]:
    """挑出『現在該輪詢』的 tracked_posts。

    篩選條件：
      - status='active'
      - last_polled_at IS NULL（剛升格還沒抓過）
        OR  now - last_polled_at >= interval_minutes_for_tier(polling_tier)

    SQLite 不擅長表達『last_polled_at + interval(tier)』，所以在 Python 端
    filter。個位數使用者（tracked_posts < 1000）下成本可忽略。
    """
    now = _ensure_utc(now) or datetime.now(timezone.utc)
    actives = session.scalars(
        select(TrackedPost).where(TrackedPost.status == ACTIVE_STATUS)
    ).all()
    due: list[TrackedPost] = []
    for tp in actives:
        last = _ensure_utc(tp.last_polled_at)
        if last is None:
            due.append(tp)
            continue
        interval = interval_minutes_for_tier(tp.polling_tier)
        if interval is None:
            # tier 字串怪掉（資料污染），先輪一次讓 capture 重設 tier
            due.append(tp)
            continue
        if (now - last) >= timedelta(minutes=interval):
            due.append(tp)
    return due


def capture_snapshot(
    session: Session,
    scraper: RedditScraper,
    tracked: TrackedPost,
    *,
    now: datetime | None = None,
) -> SnapshotResult:
    """對單一 tracked_post 抓 snapshot；更新 last_polled_at / polling_tier / status。

    錯誤處理：
      - scraper.fetch_post raise → 寫 error 但保留 last_polled_at（避免下次又馬上重試壓垮）
      - fetch_post 回 None（404 / 403）→ 直接 archived，不寫 snapshot
      - age > 30 天 → 仍寫一筆 final snapshot 然後 archived
    """
    now = _ensure_utc(now) or datetime.now(timezone.utc)
    candidate = tracked.candidate or session.get(
        CandidatePost, tracked.candidate_post_id
    )
    if candidate is None:
        logger.error(
            "capture_snapshot: tracked=%d 找不到 candidate_post_id=%d",
            tracked.id, tracked.candidate_post_id,
        )
        tracked.last_polled_at = now
        return SnapshotResult(
            tracked_post_id=tracked.id,
            captured=False,
            error="candidate_missing",
        )

    age_h = _age_hours(candidate, now)
    new_tier = tier_for_age(age_h)
    tier_changed: tuple[str, str] | None = None
    if new_tier is not None and new_tier != tracked.polling_tier:
        tier_changed = (tracked.polling_tier, new_tier)

    try:
        payload = scraper.fetch_post(candidate.reddit_post_id)
    except Exception as e:  # noqa: BLE001 — 不阻塞 batch
        logger.warning(
            "fetch_post(%s) failed: %s", candidate.reddit_post_id, e
        )
        tracked.last_polled_at = now
        return SnapshotResult(
            tracked_post_id=tracked.id,
            captured=False,
            error=str(e),
        )

    if payload is None:
        # 貼文消失 / 隔離 — 仍記下 last_polled_at 並 archived 防再撈
        tracked.last_polled_at = now
        tracked.status = ARCHIVED_STATUS
        logger.info(
            "tracked=%d post=%s vanished (fetch_post=None) → archived",
            tracked.id, candidate.reddit_post_id,
        )
        return SnapshotResult(
            tracked_post_id=tracked.id, captured=False, archived=True
        )

    snap = PostSnapshot(
        tracked_post_id=tracked.id,
        score=payload.score,
        num_comments=payload.num_comments,
        upvote_ratio=payload.upvote_ratio,
    )
    session.add(snap)
    tracked.last_polled_at = now

    if new_tier is None:
        tracked.status = ARCHIVED_STATUS
        logger.info(
            "tracked=%d age=%.1fh >30d → archived (final snapshot captured)",
            tracked.id, age_h,
        )
        session.flush()
        return SnapshotResult(
            tracked_post_id=tracked.id, captured=True, archived=True
        )

    if tier_changed is not None:
        tracked.polling_tier = new_tier
        logger.info(
            "tracked=%d tier %s → %s (age=%.1fh)",
            tracked.id, tier_changed[0], tier_changed[1], age_h,
        )

    session.flush()
    return SnapshotResult(
        tracked_post_id=tracked.id,
        captured=True,
        tier_changed=tier_changed,
    )


def run_polling(
    session: Session,
    scraper: RedditScraper,
    *,
    now: datetime | None = None,
) -> PollingStat:
    """單輪 polling：select_due_posts → capture_snapshot 每一筆。"""
    now = _ensure_utc(now) or datetime.now(timezone.utc)
    due = select_due_posts(session, now=now)
    stat = PollingStat(total_due=len(due))
    for tp in due:
        result = capture_snapshot(session, scraper, tp, now=now)
        stat.snapshots.append(result)
        if result.captured:
            stat.captured += 1
        if result.archived:
            stat.archived += 1
        if result.error:
            stat.errors += 1
    logger.info(
        "polling round: due=%d captured=%d archived=%d errors=%d",
        stat.total_due, stat.captured, stat.archived, stat.errors,
    )
    return stat


__all__ = [
    "ACTIVE_STATUS",
    "ARCHIVED_STATUS",
    "PollingStat",
    "SnapshotResult",
    "TIER_ARCHIVE",
    "TIER_COOLING",
    "TIER_HOT",
    "TIER_RULES",
    "capture_snapshot",
    "interval_minutes_for_tier",
    "run_polling",
    "select_due_posts",
    "tier_for_age",
]

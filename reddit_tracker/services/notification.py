"""後續推送選單 — M5.8。

兩種推送：

  1. **Milestone immediate push**
     `related_posts.is_milestone=True AND notified_at IS NULL`
     → 每篇即時送一則 Telegram 訊息 → mark notified。
     由 scheduler 在 breaking_check 同節奏（每 10 min）跑。

  2. **Daily digest**
     非 milestone 但今天新出現的 related events，依 tracked_post 聚合，每篇
     tracked 一段。由 daily_push_job 跑完候選推送後接著送（也可單獨呼叫）。
     單一 digest 訊息送出後，把當日參與聚合的 RelatedPost 都 mark notified。

本層只負責「挑、加工、收尾」三件事，實際 send 在 `bot/related_sender.py`。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import CandidatePost, RelatedPost, TrackedPost
from .polling import ACTIVE_STATUS

logger = logging.getLogger(__name__)


# 一次 digest 最多挑幾條 related event（避免訊息過長 / Telegram 4096 char 限制）
DIGEST_MAX_ENTRIES_PER_TRACKED = 5
DIGEST_LOOKBACK_HOURS = 24


def _ensure_utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Milestone push
# ---------------------------------------------------------------------------


@dataclass
class PendingMilestone:
    related: RelatedPost
    tracked: TrackedPost
    candidate: CandidatePost


def fetch_pending_milestones(
    session: Session, *, limit: int = 20
) -> list[PendingMilestone]:
    """is_milestone=True 且 notified_at IS NULL，依 discovered_at 排序回傳。

    join tracked + candidate 一起拿，呼叫端不需要再 query。
    """
    rows = session.execute(
        select(RelatedPost, TrackedPost, CandidatePost)
        .join(TrackedPost, TrackedPost.id == RelatedPost.tracked_post_id)
        .join(CandidatePost, CandidatePost.id == TrackedPost.candidate_post_id)
        .where(
            RelatedPost.is_milestone.is_(True),
            RelatedPost.notified_at.is_(None),
            TrackedPost.status == ACTIVE_STATUS,
        )
        .order_by(RelatedPost.discovered_at.asc())
        .limit(limit)
    ).all()
    return [PendingMilestone(r, t, c) for r, t, c in rows]


def mark_notified(
    session: Session,
    related_ids: list[int],
    *,
    now: datetime | None = None,
) -> int:
    """把指定 related rows 的 notified_at 寫成 now。回實際更新筆數。"""
    if not related_ids:
        return 0
    now = _ensure_utc(now) or datetime.now(timezone.utc)
    n = 0
    for rid in related_ids:
        rp = session.get(RelatedPost, rid)
        if rp is None or rp.notified_at is not None:
            continue
        rp.notified_at = now
        n += 1
    session.flush()
    return n


# ---------------------------------------------------------------------------
# Daily digest
# ---------------------------------------------------------------------------


@dataclass
class DigestEntry:
    """單一 tracked 在一份 digest 內的一段。"""

    tracked: TrackedPost
    candidate: CandidatePost
    related: list[RelatedPost] = field(default_factory=list)


def build_daily_digest(
    session: Session,
    *,
    push_date: date | None = None,
    now: datetime | None = None,
    lookback_hours: int = DIGEST_LOOKBACK_HOURS,
    max_per_tracked: int = DIGEST_MAX_ENTRIES_PER_TRACKED,
) -> list[DigestEntry]:
    """彙整過去 lookback_hours 內、尚未 notified 的非-milestone related event。

    依 tracked_post 分組，每組最多 max_per_tracked 條（取 relevance_score
    最高 / 次高）。milestone 不進 digest（它們走即時推送）。
    """
    now = _ensure_utc(now) or datetime.now(timezone.utc)
    if push_date is None:
        push_date = now.date()
    cutoff = now - timedelta(hours=lookback_hours)

    rows = session.execute(
        select(RelatedPost, TrackedPost, CandidatePost)
        .join(TrackedPost, TrackedPost.id == RelatedPost.tracked_post_id)
        .join(CandidatePost, CandidatePost.id == TrackedPost.candidate_post_id)
        .where(
            RelatedPost.is_milestone.is_(False),
            RelatedPost.notified_at.is_(None),
            RelatedPost.discovered_at >= cutoff,
            TrackedPost.status == ACTIVE_STATUS,
        )
        .order_by(RelatedPost.discovered_at.asc())
    ).all()

    by_tracked: dict[int, DigestEntry] = {}
    for r, t, c in rows:
        entry = by_tracked.get(t.id)
        if entry is None:
            entry = DigestEntry(tracked=t, candidate=c, related=[])
            by_tracked[t.id] = entry
        entry.related.append(r)

    # 每組依 relevance_score 排序，截 max_per_tracked
    for entry in by_tracked.values():
        entry.related.sort(
            key=lambda r: (r.relevance_score or 0.0), reverse=True
        )
        entry.related = entry.related[:max_per_tracked]

    return list(by_tracked.values())


__all__ = [
    "DIGEST_LOOKBACK_HOURS",
    "DIGEST_MAX_ENTRIES_PER_TRACKED",
    "DigestEntry",
    "PendingMilestone",
    "build_daily_digest",
    "fetch_pending_milestones",
    "mark_notified",
]

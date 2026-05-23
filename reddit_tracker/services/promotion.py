"""Promotion service — M5.1。

feedback.action='collect' → 在 `tracked_posts` 建一筆 row、polling_tier='hot'、
status='active'。後續輪詢由 `services/polling.py` 接手。

Idempotent on candidate_post_id：`CandidatePost.tracked` 是 `uselist=False`，
語意上一篇候選對應至多一筆 tracked。第二位使用者再 ❤️ 同篇時只回傳現有 id，
仍照樣寫 feedback row（feedback 那層自己處理 dedup）。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import CandidatePost, SubredditSource, TrackedPost

logger = logging.getLogger(__name__)


INITIAL_TIER = "hot"
ACTIVE_STATUS = "active"


@dataclass
class PromotionOutcome:
    tracked_post_id: int | None
    created: bool = False
    already_tracked: bool = False
    candidate_missing: bool = False


def promote_to_tracked(
    session: Session,
    *,
    user_id: int,
    candidate_post_id: int,
) -> PromotionOutcome:
    """把 candidate 升格為 tracked_post。Caller 負責 commit。"""
    cand = session.get(CandidatePost, candidate_post_id)
    if cand is None:
        logger.warning(
            "promote_to_tracked: candidate=%d not found", candidate_post_id
        )
        return PromotionOutcome(tracked_post_id=None, candidate_missing=True)

    existing = session.scalar(
        select(TrackedPost).where(TrackedPost.candidate_post_id == candidate_post_id)
    )
    if existing is not None:
        return PromotionOutcome(
            tracked_post_id=existing.id, already_tracked=True
        )

    tracked = TrackedPost(
        candidate_post_id=candidate_post_id,
        user_id=user_id,
        polling_tier=INITIAL_TIER,
        status=ACTIVE_STATUS,
    )
    session.add(tracked)
    session.flush()

    sub = session.scalar(
        select(SubredditSource).where(SubredditSource.name == cand.subreddit)
    )
    if sub is not None:
        sub.total_collected += 1

    logger.info(
        "promoted candidate=%d → tracked id=%d (subreddit=%s user=%d tier=%s)",
        candidate_post_id, tracked.id, cand.subreddit, user_id, INITIAL_TIER,
    )
    return PromotionOutcome(tracked_post_id=tracked.id, created=True)


__all__ = [
    "ACTIVE_STATUS",
    "INITIAL_TIER",
    "PromotionOutcome",
    "promote_to_tracked",
]

"""Feedback service — 寫使用者按鈕回饋（M4.5）。

把 DB 邏輯獨立出來不放 bot/handlers.py，主要為了：
- async telegram callback 跟 sync sqlalchemy session 解耦
- 純 sync 函式好寫單元測試（in-memory SQLite + 直接驗 row）

冪等：同 (user_id, candidate_post_id, action) 只寫一筆。第二次觸發回 duplicate=True
不重複插入，callback 端用這個資訊回 UI「已收到」即可。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import CandidatePost, Feedback

logger = logging.getLogger(__name__)


VALID_ACTIONS = {"collect", "dislike", "mute_author"}


@dataclass
class FeedbackOutcome:
    feedback_id: int | None
    candidate_missing: bool = False
    duplicate: bool = False
    invalid_action: bool = False


def record_feedback(
    session: Session,
    *,
    user_id: int,
    candidate_post_id: int,
    action: str,
) -> FeedbackOutcome:
    """寫 Feedback row。caller 負責 commit。

    Outcome 變體：
      - 成功新寫：feedback_id 有值、其餘 False
      - 已存在同樣的 (user, cand, action)：duplicate=True、回現有 id
      - candidate_post_id 不存在：candidate_missing=True、id=None
      - action 不在白名單：invalid_action=True、id=None
    """
    if action not in VALID_ACTIONS:
        logger.warning("record_feedback rejected invalid action=%r", action)
        return FeedbackOutcome(feedback_id=None, invalid_action=True)

    cand_id = session.scalar(
        select(CandidatePost.id).where(CandidatePost.id == candidate_post_id)
    )
    if cand_id is None:
        logger.warning(
            "record_feedback for unknown candidate=%d (user=%d action=%s)",
            candidate_post_id, user_id, action,
        )
        return FeedbackOutcome(feedback_id=None, candidate_missing=True)

    existing = session.scalar(
        select(Feedback).where(
            Feedback.user_id == user_id,
            Feedback.candidate_post_id == candidate_post_id,
            Feedback.action == action,
        )
    )
    if existing is not None:
        return FeedbackOutcome(feedback_id=existing.id, duplicate=True)

    fb = Feedback(
        user_id=user_id,
        candidate_post_id=candidate_post_id,
        action=action,
    )
    session.add(fb)
    session.flush()
    logger.info(
        "feedback recorded id=%d user=%d candidate=%d action=%s",
        fb.id, user_id, candidate_post_id, action,
    )
    return FeedbackOutcome(feedback_id=fb.id)


__all__ = ["FeedbackOutcome", "VALID_ACTIONS", "record_feedback"]

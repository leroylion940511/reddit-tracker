"""Milestone + digest 推送（M5.8）。

`bot/sender.py` 是 candidate push（每日 5 篇 + breaking）；本檔負責「收藏後的
後續事件」推送，介面類似但 marker 改寫 `RelatedPost.notified_at` 而非
`DailyPush.pushed_at`。
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from ..services.notification import DigestEntry, PendingMilestone, mark_notified
from .formatter import format_digest_message, format_milestone_message

if TYPE_CHECKING:
    from sqlalchemy.orm import Session
    from telegram import Bot

logger = logging.getLogger(__name__)


async def send_milestone(bot: Bot, chat_id: int, pending: PendingMilestone) -> bool:
    text = format_milestone_message(pending)
    try:
        await bot.send_message(
            chat_id=chat_id,
            text=text,
            parse_mode="HTML",
            disable_web_page_preview=False,
        )
        return True
    except Exception as e:  # noqa: BLE001
        logger.error(
            "send_milestone failed related=%d tracked=%d: %s",
            pending.related.id, pending.tracked.id, e,
        )
        return False


async def send_digest(bot: Bot, chat_id: int, entries: list[DigestEntry]) -> bool:
    if not entries:
        return False
    text = format_digest_message(entries)
    try:
        await bot.send_message(
            chat_id=chat_id,
            text=text,
            parse_mode="HTML",
            disable_web_page_preview=True,
        )
        return True
    except Exception as e:  # noqa: BLE001
        logger.error("send_digest failed (entries=%d): %s", len(entries), e)
        return False


async def deliver_milestones(
    bot: Bot,
    chat_id: int,
    pendings: list[PendingMilestone],
    *,
    session: Session,
) -> tuple[int, int]:
    """送一批 + 寫 notified_at 回 (sent, failed)。"""
    sent_ids: list[int] = []
    failed = 0
    for p in pendings:
        ok = await send_milestone(bot, chat_id, p)
        if ok:
            sent_ids.append(p.related.id)
        else:
            failed += 1
    if sent_ids:
        mark_notified(session, sent_ids, now=datetime.now(timezone.utc))
    return (len(sent_ids), failed)


async def deliver_digest(
    bot: Bot,
    chat_id: int,
    entries: list[DigestEntry],
    *,
    session: Session,
) -> tuple[int, int]:
    """送一封 digest（成功就 mark 所有參與聚合的 RelatedPost notified）。

    回 (sent_count=0 or 1, related_marked_count)。
    """
    if not entries:
        return (0, 0)
    ok = await send_digest(bot, chat_id, entries)
    if not ok:
        return (0, 0)
    ids = [r.id for e in entries for r in e.related]
    marked = mark_notified(session, ids, now=datetime.now(timezone.utc))
    return (1, marked)


__all__ = [
    "deliver_digest",
    "deliver_milestones",
    "send_digest",
    "send_milestone",
]

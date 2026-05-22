"""Send picks to Telegram + 回寫 daily_pushes.pushed_at（M4.5 delivery 部分）。

接 `services/feed.record_pushes()` 寫出的 DailyPush row：每送出一篇就把
`pushed_at` 補上 UTC 現在時刻，之後重啟 / 補推可知道哪些已交付。

`telegram.Bot` 屬於 python-telegram-bot 的 async API；本模組刻意不在 module
top 做 build_application()，避免 import 時就抓 token / 連網。
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from sqlalchemy import update as sa_update

from ..models import DailyPush
from ..services.feed import FeedPick
from .formatter import format_push_message

if TYPE_CHECKING:
    from sqlalchemy.orm import Session
    from telegram import Bot

logger = logging.getLogger(__name__)


async def send_pick(bot: Bot, chat_id: int, pick: FeedPick) -> bool:
    """送單篇到指定 chat。回 True/False 表示成功與否（不 raise，讓 batch 不中斷）。"""
    text, keyboard = format_push_message(pick)
    try:
        await bot.send_message(
            chat_id=chat_id,
            text=text,
            reply_markup=keyboard,
            parse_mode="HTML",
            disable_web_page_preview=False,
        )
        return True
    except Exception as e:  # noqa: BLE001
        logger.error(
            "send_message failed candidate=%d push_type=%s: %s",
            pick.candidate_post_id, pick.push_type, e,
        )
        return False


def _mark_pushed(session: Session, candidate_ids: list[int], push_date) -> None:
    """把 (push_date, candidate_id) 對應的 DailyPush.pushed_at 回填 UTC now。"""
    if not candidate_ids:
        return
    session.execute(
        sa_update(DailyPush)
        .where(
            DailyPush.push_date == push_date,
            DailyPush.candidate_post_id.in_(candidate_ids),
            DailyPush.pushed_at.is_(None),
        )
        .values(pushed_at=datetime.now(timezone.utc))
    )


async def deliver_picks(
    bot: Bot,
    chat_id: int,
    picks: list[FeedPick],
    *,
    push_date=None,
    session: Session | None = None,
) -> tuple[int, int]:
    """送一批 + 回寫 pushed_at。

    若呼叫端傳 session 進來，會在同一個 session 內回寫（caller 負責 commit）；
    若沒傳，就自己用 `session_scope()` 做一個短暫的 session。

    回傳 (sent, failed) 計數。
    """
    if not picks:
        return (0, 0)

    if push_date is None:
        push_date = datetime.now(timezone.utc).date()

    sent_ids: list[int] = []
    failed = 0
    for pick in picks:
        ok = await send_pick(bot, chat_id, pick)
        if ok:
            sent_ids.append(pick.candidate_post_id)
        else:
            failed += 1

    if sent_ids:
        if session is not None:
            _mark_pushed(session, sent_ids, push_date)
        else:
            from ..db import session_scope
            with session_scope() as s:
                _mark_pushed(s, sent_ids, push_date)

    return (len(sent_ids), failed)


__all__ = ["deliver_picks", "send_pick"]

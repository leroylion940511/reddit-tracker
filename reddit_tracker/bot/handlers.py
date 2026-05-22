"""Telegram handler — 指令骨架 + 三按鈕 callback（M4.5）。

設計重點：
- async telegram callback 與 sync sqlalchemy 之間用 `asyncio.to_thread` 橋接
- DB 邏輯都在 services/feedback.py，這層只解析 callback_data + 回 UI
- /feed、/saved、/ask 等先放 deferred stub，等 M4.6 / M5 / M6 再填內容
"""

from __future__ import annotations

import asyncio
import logging

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from ..db import session_scope
from ..services.feedback import FeedbackOutcome, record_feedback
from .formatter import ACTION_TO_FEEDBACK, decode_callback

logger = logging.getLogger(__name__)


HELP_TEXT = (
    "Reddit Tracker 指令：\n"
    "/start             註冊\n"
    "/help              顯示說明\n"
    "/feed              查看今日推送 (M4.6 上線)\n"
    "/saved             查看已收藏 (M5 上線)\n"
    "/ask <id>          進入問答模式 (M6 上線)\n"
)

_DEFERRED_MSG = "這個功能還沒上線，等之後的里程碑開放。"


# Callback 後回給使用者的提示文字
ACTION_REPLIES = {
    "collect": "✅ 已收藏 — 之後會自動追蹤這篇的更新",
    "dislike": "✅ 已跳過",
    "mute_author": "🔕 已靜音作者",
}

DUPLICATE_REPLY = "（先前已收到相同的回饋）"
INVALID_REPLY = "無效的按鈕回饋"
MISSING_REPLY = "找不到這篇貼文"


async def start_cmd(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
    msg = update.effective_message
    if msg is None:
        return
    await msg.reply_text(
        "嗨！這裡是 Reddit 素人爆文追蹤 Bot（v4 開發中）。\n\n" + HELP_TEXT
    )


async def help_cmd(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
    msg = update.effective_message
    if msg is None:
        return
    await msg.reply_text(HELP_TEXT)


async def deferred_cmd(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
    msg = update.effective_message
    if msg is None:
        return
    await msg.reply_text(_DEFERRED_MSG)


def _record_feedback_sync(user_id: int, candidate_id: int, action: str) -> FeedbackOutcome:
    """同步包一層 session_scope，給 async handler 用 to_thread 呼叫。"""
    with session_scope() as session:
        return record_feedback(
            session,
            user_id=user_id,
            candidate_post_id=candidate_id,
            action=action,
        )


async def feedback_callback(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """處理 inline button 點擊。callback_data 格式 `fb:<c|d|m>:<candidate_id>`。"""
    query = update.callback_query
    if query is None:
        return

    parsed = decode_callback(query.data)
    if parsed is None:
        logger.warning("ignored unparseable callback_data=%r", query.data)
        await query.answer(INVALID_REPLY)
        return

    short_action, candidate_id = parsed
    fb_action = ACTION_TO_FEEDBACK.get(short_action)
    if fb_action is None:
        logger.warning("ignored unknown short_action=%r", short_action)
        await query.answer(INVALID_REPLY)
        return

    user = update.effective_user
    user_id = user.id if user else 0

    outcome = await asyncio.to_thread(
        _record_feedback_sync, user_id, candidate_id, fb_action
    )

    if outcome.candidate_missing:
        await query.answer(MISSING_REPLY)
        return
    if outcome.invalid_action:
        await query.answer(INVALID_REPLY)
        return

    base_reply = ACTION_REPLIES[fb_action]
    reply = base_reply if not outcome.duplicate else f"{base_reply} {DUPLICATE_REPLY}"
    await query.answer(reply)

    # 把原訊息結尾追加狀態行 + 移除按鈕，避免重複點擊
    msg = query.message
    if msg is not None and msg.text:
        # 直接拿 html_text 才能保留原本的格式（粗體 / 連結）
        original = msg.text_html if msg.text_html is not None else msg.text
        new_text = f"{original}\n\n— {reply}"
        try:
            await query.edit_message_text(
                new_text,
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
                reply_markup=None,
            )
        except Exception as e:  # noqa: BLE001
            logger.warning("edit_message_text failed: %s", e)


__all__ = [
    "ACTION_REPLIES",
    "DUPLICATE_REPLY",
    "HELP_TEXT",
    "INVALID_REPLY",
    "MISSING_REPLY",
    "_record_feedback_sync",
    "deferred_cmd",
    "feedback_callback",
    "help_cmd",
    "start_cmd",
]

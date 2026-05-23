"""Telegram Application bootstrap（M4.6 骨架）。

提供：
- build_application() — 註冊 /start /help /feed /saved /ask 等 handler 與 callback handler
- run_polling()     — long polling 跑起來 bot；用於本機開發

scheduler 的 daily_push_job / breaking_check_job（M4.7）會直接拿
`telegram.Bot(token)` 配 chat_id 推送，不需透過這支 Application。
"""

from __future__ import annotations

import logging

from telegram.ext import Application, ApplicationBuilder, CallbackQueryHandler, CommandHandler

from ..config import get_settings
from . import handlers

logger = logging.getLogger(__name__)


def build_application() -> Application:
    s = get_settings()
    if not s.telegram_bot_token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is not configured")

    app = ApplicationBuilder().token(s.telegram_bot_token).build()
    app.add_handler(CommandHandler("start", handlers.start_cmd))
    app.add_handler(CommandHandler("help", handlers.help_cmd))
    # M5.9 — /saved + /timeline 上線
    app.add_handler(CommandHandler("saved", handlers.saved_cmd))
    app.add_handler(CommandHandler("timeline", handlers.timeline_cmd))
    # M4.6 / M6 placeholders
    for name in ("feed", "ask", "exit", "digest", "settings"):
        app.add_handler(CommandHandler(name, handlers.deferred_cmd))

    # 三按鈕回饋：所有 callback_data 以 'fb:' 開頭都進這個 handler
    app.add_handler(
        CallbackQueryHandler(handlers.feedback_callback, pattern=r"^fb:")
    )
    return app


def run_polling() -> None:
    """以 long polling 模式跑 bot。阻塞當前 thread。"""
    logging.basicConfig(
        level=get_settings().log_level,
        format="%(asctime)s %(levelname)s %(name)s | %(message)s",
    )
    app = build_application()
    logger.info("bot.start_polling")
    app.run_polling()


if __name__ == "__main__":
    run_polling()

"""Telegram Application bootstrap（M4.6 骨架）。

提供：
- build_application() — 註冊 /start /help /feed /saved /ask 等 handler 與 callback handler
- run_polling()     — long polling 跑起來 bot；用於本機開發

scheduler 的 daily_push_job / breaking_check_job（M4.7）會直接拿
`telegram.Bot(token)` 配 chat_id 推送，不需透過這支 Application。
"""

from __future__ import annotations

import logging

from telegram import BotCommand
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    MessageHandler,
    filters,
)

from ..config import get_settings
from . import handlers

logger = logging.getLogger(__name__)


# Telegram 端的指令選單 (setMyCommands). 描述 ≤ 256 chr 但實務上越短越好.
BOT_COMMANDS: list[BotCommand] = [
    BotCommand("start", "註冊 / 顯示介紹"),
    BotCommand("help", "查指令列表"),
    BotCommand("feed", "今日推送內容"),
    BotCommand("digest", "本週收藏動態摘要"),
    BotCommand("saved", "我的收藏列表"),
    BotCommand("timeline", "看單篇時間軸 (帶 id)"),
    BotCommand("ask", "進入問答模式 (帶 id)"),
    BotCommand("exit", "離開問答模式"),
    BotCommand("settings", "系統狀態與設定"),
]


async def _post_init(app: Application) -> None:
    """bot 啟動後自動把指令選單同步到 Telegram 端 (setMyCommands).

    沒這層的話, Telegram 客戶端的 / 自動完成清單永遠是空的或舊的;
    每次改 BOT_COMMANDS 後下次 bot 重啟即會自動 sync.
    """
    await app.bot.set_my_commands(BOT_COMMANDS)
    logger.info("bot.set_my_commands synced: %d cmds", len(BOT_COMMANDS))


def build_application() -> Application:
    s = get_settings()
    if not s.telegram_bot_token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is not configured")

    app = (
        ApplicationBuilder()
        .token(s.telegram_bot_token)
        .post_init(_post_init)
        .build()
    )
    app.add_handler(CommandHandler("start", handlers.start_cmd))
    app.add_handler(CommandHandler("help", handlers.help_cmd))
    # M5.9 — /saved + /timeline 上線
    app.add_handler(CommandHandler("saved", handlers.saved_cmd))
    app.add_handler(CommandHandler("timeline", handlers.timeline_cmd))
    # M6 — /ask /exit 上線
    app.add_handler(CommandHandler("ask", handlers.ask_cmd))
    app.add_handler(CommandHandler("exit", handlers.exit_cmd))
    # Plan C 階段補上的指令（純 DB 讀取，不依賴 comment tree）
    app.add_handler(CommandHandler("feed", handlers.feed_cmd))
    app.add_handler(CommandHandler("digest", handlers.digest_cmd))
    app.add_handler(CommandHandler("settings", handlers.settings_cmd))

    # 三按鈕回饋：所有 callback_data 以 'fb:' 開頭都進這個 handler
    app.add_handler(
        CallbackQueryHandler(handlers.feedback_callback, pattern=r"^fb:")
    )
    app.add_handler(
        CallbackQueryHandler(handlers.newsroom_feedback_callback, pattern=r"^nr:")
    )

    # M6 — active QA session 中的自由文字走 chat handler
    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handlers.chat_message)
    )
    return app


def run_polling() -> None:
    """以 long polling 模式跑 bot。阻塞當前 thread。"""
    logging.basicConfig(
        level=get_settings().log_level,
        format="%(asctime)s %(levelname)s %(name)s | %(message)s",
    )
    # httpx INFO 會把 Telegram Bot API URL 寫進 log，該 URL 內含 bot token。
    # 專案自己的 INFO log 保留，第三方 HTTP transport 僅保留 warning/error。
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    app = build_application()
    logger.info("bot.start_polling")
    app.run_polling()


if __name__ == "__main__":
    run_polling()

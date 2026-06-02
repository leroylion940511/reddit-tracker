"""一次性把 reddit_tracker/bot/app.py::BOT_COMMANDS 同步到 Telegram 端 menu.

平常 bot 啟動時 `_post_init` 已會自動 sync, 這支腳本是為了:
    - 不想重啟 bot 也要立刻刷新選單
    - 或要清空 (--clear) 重設

用法:
    uv run python scripts/refresh_bot_commands.py          # 用 BOT_COMMANDS sync
    uv run python scripts/refresh_bot_commands.py --clear  # 清空 (delete_my_commands)
    uv run python scripts/refresh_bot_commands.py --show   # 只列當前 Telegram 端的設定
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv  # noqa: E402

from reddit_tracker.bot.app import BOT_COMMANDS  # noqa: E402
from reddit_tracker.config import get_settings  # noqa: E402

load_dotenv()


async def _run(action: str) -> None:
    from telegram import Bot

    s = get_settings()
    if not s.telegram_bot_token:
        print("ERROR: TELEGRAM_BOT_TOKEN not configured (check .env)")
        sys.exit(1)

    bot = Bot(token=s.telegram_bot_token)

    if action == "show":
        current = await bot.get_my_commands()
        if not current:
            print("(Telegram 端目前沒有任何 command 設定)")
            return
        print(f"目前 Telegram 端的 {len(current)} 個指令:")
        for c in current:
            print(f"  /{c.command} — {c.description}")
        return

    if action == "clear":
        await bot.delete_my_commands()
        print("✓ Telegram 端 commands 清空。")
        return

    await bot.set_my_commands(BOT_COMMANDS)
    print(f"✓ 已 sync {len(BOT_COMMANDS)} 個指令到 Telegram:")
    for c in BOT_COMMANDS:
        print(f"  /{c.command} — {c.description}")
    print("\n提示: Telegram 客戶端可能 cache 舊菜單, 重新進入聊天視窗或重啟 app 才看得到新版。")


def main() -> None:
    if "--clear" in sys.argv:
        action = "clear"
    elif "--show" in sys.argv:
        action = "show"
    else:
        action = "sync"
    asyncio.run(_run(action))


if __name__ == "__main__":
    main()

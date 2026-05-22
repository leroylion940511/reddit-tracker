"""抓 Telegram chat_id 的小工具（M4.7 helper）。

用法：
    1. 確認 .env 已設 TELEGRAM_BOT_TOKEN
    2. uv run python scripts/m4_capture_chat_id.py
    3. 在 Telegram 對 bot 發任何訊息（例如 /start）
    4. 本程式會印 chat_id（連同 username / first_name）並退出
    5. 把 chat_id 貼回 .env 的 TELEGRAM_CHAT_ID

實作走 getUpdates long polling（不需要動 webhook），最多輪詢 120 秒。
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import requests

from reddit_tracker.config import get_settings


def main() -> int:
    s = get_settings()
    token = s.telegram_bot_token
    if not token:
        print("ERROR: TELEGRAM_BOT_TOKEN 未設（請看 .env）", file=sys.stderr)
        return 2

    base = f"https://api.telegram.org/bot{token}"

    # 1. 先 getMe 驗 token
    me = requests.get(f"{base}/getMe", timeout=10).json()
    if not me.get("ok"):
        print(f"ERROR: token 無效 — {me}", file=sys.stderr)
        return 2
    bot_name = me["result"]["username"]
    print(f"[ok] bot 是 @{bot_name}")
    print(f"[..] 請去 Telegram 對 @{bot_name} 發任何訊息（例如 /start）")
    print(f"[..] 最多等 120 秒...")

    # 2. 找出當前最大 update_id，避免拿到舊訊息
    initial = requests.get(f"{base}/getUpdates", timeout=10).json()
    last_id = 0
    for upd in initial.get("result", []):
        last_id = max(last_id, upd["update_id"])

    deadline = time.time() + 120
    while time.time() < deadline:
        resp = requests.get(
            f"{base}/getUpdates",
            params={"offset": last_id + 1, "timeout": 25},
            timeout=30,
        ).json()
        if not resp.get("ok"):
            print(f"[warn] getUpdates not ok: {resp}", file=sys.stderr)
            time.sleep(2)
            continue
        for upd in resp.get("result", []):
            last_id = max(last_id, upd["update_id"])
            msg = upd.get("message") or upd.get("edited_message") or upd.get("callback_query", {}).get("message")
            if not msg or "chat" not in msg:
                continue
            chat = msg["chat"]
            print()
            print(f"  chat_id  : {chat['id']}")
            print(f"  type     : {chat.get('type')}")
            for k in ("username", "first_name", "last_name", "title"):
                if k in chat:
                    print(f"  {k:9s}: {chat[k]}")
            print()
            print(f"請把這行加到 .env：")
            print(f"  TELEGRAM_CHAT_ID={chat['id']}")
            return 0

    print("[timeout] 120 秒內沒收到任何訊息。請再跑一次。", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

"""檢查零 API-key LLM browser session readiness，不送 prompt、不讀既有對話。"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from reddit_tracker.config import get_settings  # noqa: E402
from reddit_tracker.llm.web_chat import WebSessionChat, WebSessionError  # noqa: E402


def main() -> int:
    settings = get_settings()
    chat = WebSessionChat(
        provider=settings.web_llm_provider,
        cdp_url=settings.web_llm_cdp_url,
        timeout=settings.web_llm_timeout_seconds,
        poll_interval=settings.web_llm_poll_interval_seconds,
        settle_seconds=settings.web_llm_settle_seconds,
        lock_path=settings.web_llm_lock_path,
    )
    try:
        status = chat.probe()
    except WebSessionError as exc:
        print(f"NOT READY: {exc}")
        return 1
    if status.get("logged_out") or not status.get("ready"):
        print(f"NOT READY: {status}")
        return 1
    print(f"READY: {chat.provider} at {status.get('url')} (no API key used)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

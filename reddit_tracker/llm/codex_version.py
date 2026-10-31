"""Codex CLI 版本守門：實際 `codex --version` 要等於 `DAILY_MODEL_VERSION` 鎖定的版本。

- `probe_cli_version(binary)`：跑 `<binary> --version`（不是 LLM 呼叫），回傳 `0.166.0` 這種版本字串；
  找不到 binary、exit 非 0、逾時、看不懂輸出都回 None。
- `locked_cli_version(model_version)`：從 `"<model> | codex-cli <ver> | reasoning_effort=<x>"` 取出 `<ver>`。
- `actual_model_version(locked, actual)`：把鎖定字串的 `codex-cli` 段換成實際版本；讀不到實際版本時
  寫成 `codex-cli unknown(locked <ver>)`，llm_records 一看就知道沒有實測。
- `check_codex_version(settings)`：排程啟動與每天 06:00 準備前各呼叫一次。不一致或讀不到就記 ERROR
  並送 Telegram 警告；任何例外都吞掉，不擋出刊。

注意：replay 的 `request_hash` 不含 CLI 版本，換 CLI 版本不會讓既有錄音失效。
"""

from __future__ import annotations

import asyncio
import logging
import re
import subprocess

logger = logging.getLogger(__name__)

PROBE_TIMEOUT_SECONDS = 10.0
_VERSION_OUTPUT = re.compile(r"codex-cli\s+(\S+)")
_LOCKED_SEGMENT = re.compile(r"codex-cli\s+([^|\s]+)")


def parse_cli_version(output: str | None) -> str | None:
    """`codex-cli 0.166.0` → `0.166.0`；看不懂回 None。"""
    match = _VERSION_OUTPUT.search(output or "")
    return match.group(1) if match else None


def probe_cli_version(binary: str, *, timeout: float = PROBE_TIMEOUT_SECONDS) -> str | None:
    try:
        proc = subprocess.run([binary, "--version"], capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    return parse_cli_version(proc.stdout) or parse_cli_version(proc.stderr)


def locked_cli_version(model_version: str | None) -> str | None:
    match = _LOCKED_SEGMENT.search(model_version or "")
    return match.group(1) if match else None


def actual_model_version(locked: str, actual: str | None) -> str:
    """鎖定字串的 `codex-cli` 段換成實測版本；鎖定字串沒有這段就原樣回傳。"""
    pinned = locked_cli_version(locked)
    if pinned is None:
        return locked
    segment = f"codex-cli {actual}" if actual else f"codex-cli unknown(locked {pinned})"
    return _LOCKED_SEGMENT.sub(segment, locked, count=1)


def send_telegram_warning(token: str, chat_id: str | int, text: str) -> None:
    from telegram import Bot

    async def send() -> None:
        async with Bot(token=token) as bot:
            await bot.send_message(chat_id=int(chat_id), text=text, disable_web_page_preview=True)

    asyncio.run(send())


def check_codex_version(settings, *, notify: bool = True) -> bool | None:
    """True＝版本一致；False＝不一致或讀不到（已記 ERROR／送警告）；None＝不適用而跳過。永不拋例外。"""
    try:
        if getattr(settings, "daily_writer", None) != "codex":
            logger.debug("codex version guard skipped: daily_writer=%s", getattr(settings, "daily_writer", None))
            return None
        binary = settings.codex_bin
        locked = locked_cli_version(getattr(settings, "daily_model_version", None))
        if locked is None:
            logger.debug("codex version guard skipped: DAILY_MODEL_VERSION has no codex-cli segment")
            return None
        actual = probe_cli_version(binary)
        if actual == locked:
            logger.info("codex version guard ok: codex-cli %s (bin=%s)", actual, binary)
            return True
        message = (
            f"codex version guard: codex-cli {actual or 'unreadable'} != locked {locked} (bin={binary})"
        )
        logger.error(message)
        if notify:
            token, chat_id = getattr(settings, "telegram_bot_token", None), getattr(settings, "telegram_chat_id", None)
            if token and chat_id:
                send_telegram_warning(token, chat_id, f"⚠️ {message}")
            else:
                logger.warning("codex version guard: Telegram not configured; warning only logged")
        return False
    except Exception:  # noqa: BLE001 — 守門失敗不能擋出刊
        logger.exception("codex version guard failed")
        return False

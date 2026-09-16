"""Telegram delivery for an already-drafted newsroom edition.

Formatting is plain text on purpose: Reddit titles and links are user content,
so no HTML escaping or parse-mode surprises can alter the newspaper.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from .rendering import EditionView

TELEGRAM_SAFE_LENGTH = 3_700


def _item_text(item) -> str:
    sources = "\n".join(
        f"原帖｜r/{source.subreddit}｜{source.original_title}\n{source.permalink}"
        for source in item.sources
    )
    warning = f"\n提醒：{'、'.join(item.warnings)}" if item.warnings else ""
    return (
        f"{item.position:02d}｜【{'專題' if item.kind == 'feature' else '短報'}】{item.headline_zh}\n"
        f"{item.body_zh}\n"
        f"為什麼值得看：{item.why_it_matters}{warning}\n{sources}"
    ).strip()


def format_telegram_messages(view: EditionView, *, preview: bool = False) -> list[str]:
    """Split a full edition at article boundaries below Telegram's 4096 limit."""
    mode = "（試刊 preview）" if preview else ""
    header = (
        f"🗞️ AI 編輯室每日報｜{view.edition_date}{mode}\n"
        f"讀者版：{view.reader_summary}\n"
        "素材來自公開 Reddit 討論；原作者說法未經獨立查證。"
    )
    messages: list[str] = []
    current = header
    for item in view.items:
        article = _item_text(item)
        candidate = f"{current}\n\n{article}"
        if len(candidate) <= TELEGRAM_SAFE_LENGTH:
            current = candidate
            continue
        messages.append(current)
        # An unusually long original title may itself require a safe split.
        if len(article) <= TELEGRAM_SAFE_LENGTH:
            current = article
        else:
            for start in range(0, len(article), TELEGRAM_SAFE_LENGTH):
                messages.append(article[start:start + TELEGRAM_SAFE_LENGTH])
            current = ""
    if current:
        messages.append(current)
    if not messages:
        raise ValueError("cannot send an empty edition")
    return messages


async def send_telegram_messages(
    *,
    token: str,
    chat_id: int,
    messages: list[str],
    send: Callable[[str], Awaitable[int]] | None = None,
) -> list[int]:
    """Send messages sequentially and return Telegram message IDs.

    `send` is injectable for tests. Production owns the Bot lifecycle here so
    the scheduler does not leave a network session open.
    """
    if send is not None:
        return [await send(message) for message in messages]

    from telegram import Bot

    async with Bot(token=token) as bot:
        ids: list[int] = []
        for message in messages:
            delivered = await bot.send_message(
                chat_id=chat_id,
                text=message,
                disable_web_page_preview=True,
            )
            ids.append(delivered.message_id)
        return ids


__all__ = ["TELEGRAM_SAFE_LENGTH", "format_telegram_messages", "send_telegram_messages"]

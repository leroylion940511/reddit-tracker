"""Telegram delivery for an already-drafted newsroom edition.

Formatting is plain text on purpose: Reddit titles and links are user content,
so no HTML escaping or parse-mode surprises can alter the newspaper.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from .rendering import EditionView

TELEGRAM_SAFE_LENGTH = 3_700
NEWSROOM_CALLBACK_PREFIX = "nr"
NEWSROOM_ACTION_MORE = "m"
NEWSROOM_ACTION_LESS = "l"
NEWSROOM_ACTION_FOLLOW = "f"
NEWSROOM_ACTIONS = {
    NEWSROOM_ACTION_MORE: "more",
    NEWSROOM_ACTION_LESS: "less",
    NEWSROOM_ACTION_FOLLOW: "follow",
}


@dataclass(frozen=True)
class TelegramDeliveryMessage:
    text: str
    edition_item_id: int | None = None


def encode_newsroom_callback(action: str, edition_item_id: int) -> str:
    return f"{NEWSROOM_CALLBACK_PREFIX}:{action}:{edition_item_id}"


def decode_newsroom_callback(data: str | None) -> tuple[str, int] | None:
    if not data:
        return None
    prefix, separator, rest = data.partition(":")
    action, separator_two, item_id = rest.partition(":")
    if prefix != NEWSROOM_CALLBACK_PREFIX or not separator or not separator_two:
        return None
    try:
        return action, int(item_id)
    except ValueError:
        return None


def _item_text(item) -> str:
    sources = "\n".join(
        f"原帖｜r/{source.subreddit}｜{source.original_title}\n{source.permalink}"
        for source in item.sources
    )
    warning = f"\n提醒：{'、'.join(item.warnings)}" if item.warnings else ""
    kind = {"feature": "專題", "breaking": "早報快訊"}.get(item.kind, "短報")
    return (
        f"{item.position:02d}｜【{kind}】{item.headline_zh}\n"
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


def format_telegram_delivery_messages(view: EditionView) -> list[TelegramDeliveryMessage]:
    """One source-complete article per message, with item-specific feedback.

    A Telegram keyboard belongs to a message rather than an article within a
    combined message. Emitting article boundaries separately keeps ❤️／🚫／👀
    feedback unambiguous while preserving a source-complete, size-safe body.
    """
    header = (
        f"🗞️ AI 編輯室每日報｜{view.edition_date}\n"
        f"讀者版：{view.reader_summary}\n"
        "素材來自公開 Reddit 討論；原作者說法未經獨立查證。"
    )
    messages = [TelegramDeliveryMessage(header)]
    for item in view.items:
        article = _item_text(item)
        chunks = [article[index:index + TELEGRAM_SAFE_LENGTH] for index in range(0, len(article), TELEGRAM_SAFE_LENGTH)]
        if not chunks:
            continue
        for chunk in chunks[:-1]:
            messages.append(TelegramDeliveryMessage(chunk))
        messages.append(TelegramDeliveryMessage(chunks[-1], edition_item_id=item.id))
    if len(messages) == 1:
        raise ValueError("cannot send an empty edition")
    return messages


async def send_telegram_messages(
    *,
    token: str,
    chat_id: int,
    messages: list[str | TelegramDeliveryMessage],
    send: Callable[[str], Awaitable[int]] | None = None,
) -> list[int]:
    """Send messages sequentially and return Telegram message IDs.

    `send` is injectable for tests. Production owns the Bot lifecycle here so
    the scheduler does not leave a network session open. Callers must treat an
    exception as a potentially partial delivery: Telegram cannot atomically
    send a whole multi-message edition.
    """
    if send is not None:
        return [await send(message.text if isinstance(message, TelegramDeliveryMessage) else message) for message in messages]

    from telegram import Bot

    async with Bot(token=token) as bot:
        ids: list[int] = []
        for message in messages:
            payload = message if isinstance(message, TelegramDeliveryMessage) else TelegramDeliveryMessage(message)
            reply_markup = _feedback_keyboard(payload.edition_item_id) if payload.edition_item_id is not None else None
            delivered = await bot.send_message(
                chat_id=chat_id,
                text=payload.text,
                disable_web_page_preview=True,
                reply_markup=reply_markup,
            )
            ids.append(delivered.message_id)
    return ids


def _feedback_keyboard(edition_item_id: int):
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup

    return InlineKeyboardMarkup([[
        InlineKeyboardButton("❤️ 多看", callback_data=encode_newsroom_callback(NEWSROOM_ACTION_MORE, edition_item_id)),
        InlineKeyboardButton("🚫 少看", callback_data=encode_newsroom_callback(NEWSROOM_ACTION_LESS, edition_item_id)),
        InlineKeyboardButton("👀 追後續", callback_data=encode_newsroom_callback(NEWSROOM_ACTION_FOLLOW, edition_item_id)),
    ]])


__all__ = [
    "NEWSROOM_ACTIONS",
    "TELEGRAM_SAFE_LENGTH",
    "TelegramDeliveryMessage",
    "decode_newsroom_callback",
    "encode_newsroom_callback",
    "format_telegram_delivery_messages",
    "format_telegram_messages",
    "send_telegram_messages",
]

"""Telegram newspaper formatting remains source-complete and size-safe."""

from __future__ import annotations

import asyncio

from reddit_tracker.newsroom.publisher import TELEGRAM_SAFE_LENGTH, format_telegram_messages, send_telegram_messages
from reddit_tracker.newsroom.rendering import EditionView, ItemView, SourceView


def _view(*, body_size: int = 80) -> EditionView:
    return EditionView(
        edition_date="2026-09-17",
        reader_summary="多看人際與日常。",
        artifacts=[],
        items=[
            ItemView(
                position=position,
                kind="feature" if position == 8 else "brief",
                headline_zh=f"第 {position} 則新聞",
                body_zh="內容" * body_size,
                why_it_matters="保留來源，讓讀者自行判斷。",
                confidence="low",
                warnings=[],
                sources=[SourceView("Original Reddit title", "askreddit", f"https://reddit.example/{position}")],
            )
            for position in range(1, 9)
        ],
    )


def test_newspaper_messages_keep_source_title_and_link_below_limit():
    messages = format_telegram_messages(_view(body_size=500))

    assert all(len(message) <= TELEGRAM_SAFE_LENGTH for message in messages)
    joined = "\n".join(messages)
    assert "Original Reddit title" in joined
    assert "https://reddit.example/8" in joined


def test_sender_is_injectable_for_no_network_verification():
    sent: list[str] = []

    async def fake_send(message: str) -> int:
        sent.append(message)
        return len(sent)

    ids = asyncio.run(send_telegram_messages(token="unused", chat_id=1, messages=["a", "b"], send=fake_send))

    assert ids == [1, 2]
    assert sent == ["a", "b"]

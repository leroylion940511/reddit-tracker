"""Telegram newspaper formatting remains source-complete and size-safe."""

from __future__ import annotations

import asyncio

from reddit_tracker.newsroom.publisher import (
    TELEGRAM_SAFE_LENGTH,
    decode_newsroom_callback,
    format_telegram_delivery_messages,
    format_telegram_messages,
    send_telegram_messages,
)
from reddit_tracker.newsroom.rendering import ArtifactView, EditionView, ItemView, SourceView, render_html


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
                id=position,
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


def test_delivery_messages_attach_distinct_feedback_to_each_article():
    messages = format_telegram_delivery_messages(_view())

    assert messages[0].edition_item_id is None
    assert [message.edition_item_id for message in messages[1:]] == list(range(1, 9))
    assert decode_newsroom_callback("nr:m:8") == ("m", 8)


def test_sender_is_injectable_for_no_network_verification():
    sent: list[str] = []

    async def fake_send(message: str) -> int:
        sent.append(message)
        return len(sent)

    ids = asyncio.run(send_telegram_messages(token="unused", chat_id=1, messages=["a", "b"], send=fake_send))

    assert ids == [1, 2]
    assert sent == ["a", "b"]


def test_html_limits_large_artifact_source_lists():
    source = SourceView("Original Reddit title", "askreddit", "https://reddit.example/1")
    view = EditionView(
        edition_date="2026-09-17",
        reader_summary="多看人際與日常。",
        items=[],
        artifacts=[ArtifactView("scout", "succeeded", 1, "摘要", None, [source] * 12, source_count=100)],
    )

    page = render_html(view)

    assert "顯示 12 / 100 個來源" in page
    assert page.count("Original Reddit title") == 12

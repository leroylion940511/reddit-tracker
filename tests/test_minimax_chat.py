"""M6 — multi-turn chat client (MiniMax + Fake)."""

from __future__ import annotations

import pytest

from reddit_tracker.llm.minimax_chat import (
    ChatResult,
    FakeChat,
    MinimaxChat,
    build_chat,
    estimate_cost,
)


def test_estimate_cost_basic():
    # 1k input + 1k output → 0.0002 + 0.0011 = 0.0013
    c = estimate_cost(1000, 1000)
    assert c == pytest.approx(0.0013, rel=1e-3)


def test_fake_chat_default_reply():
    chat = FakeChat()
    result = chat.complete(
        system="sys", messages=[{"role": "user", "content": "嗨"}]
    )
    assert isinstance(result, ChatResult)
    assert "(fake reply)" in result.content
    assert result.input_tokens == 1500
    assert result.output_tokens == 80
    assert result.cost_usd is not None
    assert len(chat.calls) == 1


def test_fake_chat_custom_factory():
    chat = FakeChat(factory=lambda sys, msgs: "客製化")
    out = chat.complete(system="x", messages=[{"role": "user", "content": "?"}])
    assert out.content == "客製化"


def test_fake_chat_raise_exc():
    chat = FakeChat(raise_exc=RuntimeError("nope"))
    with pytest.raises(RuntimeError):
        chat.complete(system="x", messages=[{"role": "user", "content": "?"}])


def test_build_chat_falls_back_when_no_key(monkeypatch):
    from reddit_tracker import config

    config.get_settings.cache_clear()
    monkeypatch.setenv("MINIMAX_API_KEY", "")
    chat = build_chat()
    assert isinstance(chat, FakeChat)
    config.get_settings.cache_clear()


def test_minimax_chat_requires_key(monkeypatch):
    from reddit_tracker import config

    config.get_settings.cache_clear()
    monkeypatch.setenv("MINIMAX_API_KEY", "")
    with pytest.raises(RuntimeError):
        MinimaxChat()
    config.get_settings.cache_clear()

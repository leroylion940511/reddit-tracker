"""零 API-key browser provider 的 unit tests；不連 Chrome 或任何 LLM 網站。"""

from __future__ import annotations

import pytest
import websocket

from reddit_tracker.llm.haiku import build_user_prompt
from reddit_tracker.llm.minimax_chat import ChatResult, build_chat
from reddit_tracker.llm.web_chat import WebSessionChat, WebSessionScorer, _clean_response_text
from reddit_tracker.models import CandidatePost


def test_web_session_rejects_non_loopback_cdp():
    with pytest.raises(ValueError, match="loopback"):
        WebSessionChat(cdp_url="http://192.168.1.50:9222")


def test_chatgpt_adapter_covers_current_mobile_composer_and_zh_send_button():
    adapter = WebSessionChat().adapter
    assert "#mobile-composer-prompt" in adapter.input_selectors
    assert 'button[aria-label="傳送訊息"]' in adapter.send_button_selectors
    assert 'li:has(button[aria-label="複製回應"])' in adapter.response_selectors


def test_response_text_removes_chatgpt_ui_label_only():
    assert _clean_response_text("ChatGPT 說：\n\nQA_OK") == "QA_OK"
    assert _clean_response_text("ChatGPT said: PONG") == "PONG"
    assert _clean_response_text("actual response") == "actual response"


def test_web_session_rejects_unknown_provider():
    with pytest.raises(ValueError, match="WEB_LLM_PROVIDER"):
        WebSessionChat(provider="claude")


def test_web_session_explains_chrome_origin_allowlist(monkeypatch):
    chat = WebSessionChat()
    exc = websocket.WebSocketBadStatusException("forbidden", 403, {}, b"")
    monkeypatch.setattr(websocket, "create_connection", lambda *_args, **_kwargs: (_ for _ in ()).throw(exc))
    with pytest.raises(Exception, match="remote-allow-origins=http://127.0.0.1:9222"):
        chat._evaluate("ws://127.0.0.1:9222/devtools/page/test", "1")


def test_web_session_evaluate_closes_websocket_without_context_manager(monkeypatch):
    class FakeSocket:
        sent: list[str]
        closed: bool

        def __init__(self):
            self.sent = []
            self.closed = False

        def send(self, payload):
            self.sent.append(payload)

        def recv(self):
            return '{"id": 1, "result": {"result": {"value": {"ready": true}}}}'

        def close(self):
            self.closed = True

    fake = FakeSocket()
    monkeypatch.setattr(websocket, "create_connection", lambda *_args, **_kwargs: fake)
    result = WebSessionChat()._evaluate("ws://127.0.0.1:9222/devtools/page/test", "1 + 1")

    assert result == {"ready": True}
    assert fake.closed
    assert '"method": "Runtime.evaluate"' in fake.sent[0]


def test_web_session_complete_waits_for_new_stable_response(monkeypatch, tmp_path):
    chat = WebSessionChat(
        provider="chatgpt",
        timeout=2,
        poll_interval=0.001,
        settle_seconds=0,
        lock_path=str(tmp_path / "web-llm.lock"),
    )
    states = iter(
        [
            {"count": 1, "text": "old response", "thinking": False},
            {"count": 2, "text": "new response", "thinking": False},
            {"count": 2, "text": "new response", "thinking": False},
        ]
    )
    sent: list[str] = []
    state_calls: list[dict] = []

    def response_state(_url, **kwargs):
        state_calls.append(kwargs)
        return next(states)

    monkeypatch.setattr(chat, "_find_tab_ws_url", lambda: "ws://127.0.0.1:9222/devtools/page/test")
    monkeypatch.setattr(chat, "_response_state", response_state)
    monkeypatch.setattr(chat, "_send_prompt", lambda _url, prompt: sent.append(prompt))

    out = chat.complete(
        system="system rules",
        messages=[{"role": "user", "content": "latest question"}],
    )

    assert out == ChatResult(content="new response", cost_usd=0.0)
    assert "system rules" in sent[0]
    assert "latest question" in sent[0]
    assert state_calls == [{}, {"text_after": 1}, {"text_after": 1}]


def test_web_session_scorer_uses_existing_json_contract(monkeypatch):
    raw = (
        '{"story_potential": 0.6, "emotional_pull": 0.7, "grassroots": 0.8, '
        '"novelty": 0.5, "authenticity": 0.9, "verdict": "track", "reason": "符合條件"}'
    )
    monkeypatch.setattr(
        WebSessionChat,
        "complete",
        lambda self, **_kwargs: ChatResult(content=raw, cost_usd=0.0),
    )
    post = CandidatePost(
        reddit_post_id="web-test", subreddit="taiwan", title="標題", selftext="內容"
    )
    verdict = WebSessionScorer(provider="gemini").score(post)

    assert verdict.verdict == "track"
    assert verdict.cost_usd == 0.0
    assert "Subreddit: r/taiwan" in build_user_prompt(post)


def test_build_chat_uses_web_provider_without_api_key(monkeypatch):
    from reddit_tracker import config

    config.get_settings.cache_clear()
    monkeypatch.setenv("LLM_PROVIDER", "web")
    monkeypatch.setenv("WEB_LLM_PROVIDER", "gemini")
    monkeypatch.setenv("MINIMAX_API_KEY", "")
    chat = build_chat()
    assert isinstance(chat, WebSessionChat)
    assert chat.provider == "web_gemini"
    config.get_settings.cache_clear()

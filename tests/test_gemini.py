"""Gemini API provider tests; all HTTP responses are mocked."""

from __future__ import annotations

from types import SimpleNamespace

from reddit_tracker.llm.gemini import GeminiChat, GeminiQuotaExhausted, GeminiScorer
from reddit_tracker.llm.minimax_chat import FakeChat
from reddit_tracker.models import CandidatePost


class _Response:
    def __init__(self, data, status_code: int = 200, headers=None):
        self._data = data
        self.status_code = status_code
        self.headers = headers or {}
        self.ok = status_code < 400

    def json(self):
        return self._data


def _success_response(text: str) -> _Response:
    return _Response({
        "candidates": [{"content": {"parts": [{"text": text}]}}],
        "usageMetadata": {
            "promptTokenCount": 123,
            "candidatesTokenCount": 45,
            "cachedContentTokenCount": 6,
        },
    })


def test_gemini_scorer_uses_json_mode_and_parses_usage(monkeypatch, tmp_path):
    scorer = GeminiScorer(
        api_key="test-key",
        model="gemini-test",
        daily_limit=10,
        requests_per_minute=60,
        state_path=str(tmp_path / "quota.json"),
    )
    captured = {}
    raw = ('{"story_potential":0.7,"emotional_pull":0.8,"grassroots":0.9,'
           '"novelty":0.6,"authenticity":0.9,"verdict":"track","reason":"符合"}')

    def post(url, *, json, timeout):
        captured.update(url=url, payload=json, timeout=timeout)
        return _success_response(raw)

    monkeypatch.setattr(scorer._client._session, "post", post)
    verdict = scorer.score(CandidatePost(reddit_post_id="g1", subreddit="taiwan", title="標題", selftext="內容"))

    assert verdict.verdict == "track"
    assert verdict.input_tokens == 123
    assert verdict.output_tokens == 45
    assert verdict.cost_usd == 0.0
    assert captured["url"].endswith("/gemini-test:generateContent")
    assert captured["payload"]["generationConfig"]["responseMimeType"] == "application/json"
    assert captured["payload"]["systemInstruction"]["parts"]


def test_gemini_chat_maps_roles_and_usage(monkeypatch, tmp_path):
    chat = GeminiChat(
        api_key="test-key",
        model="gemini-test",
        daily_limit=10,
        requests_per_minute=60,
        state_path=str(tmp_path / "quota.json"),
    )
    captured = {}

    def post(_url, *, json, timeout):
        captured["payload"] = json
        return _success_response("回答")

    monkeypatch.setattr(chat._client._session, "post", post)
    result = chat.complete(system="規則", messages=[{"role": "user", "content": "問題"}, {"role": "assistant", "content": "前答"}])

    assert result.content == "回答"
    assert result.input_tokens == 123
    assert result.output_tokens == 45
    assert result.cached_tokens == 6
    assert result.cost_usd == 0.0
    assert [item["role"] for item in captured["payload"]["contents"]] == ["user", "model"]


def test_gemini_quota_uses_fallback_for_scoring(monkeypatch, tmp_path):
    fallback = SimpleNamespace(score=lambda _post: "fallback verdict")
    scorer = GeminiScorer(
        api_key="test-key",
        model="gemini-test",
        daily_limit=10,
        requests_per_minute=60,
        state_path=str(tmp_path / "quota.json"),
        fallback=fallback,
    )
    monkeypatch.setattr(
        scorer._client,
        "complete",
        lambda **_kwargs: (_ for _ in ()).throw(GeminiQuotaExhausted("quota")),
    )
    post = CandidatePost(reddit_post_id="g2", subreddit="taiwan", title="標題", selftext="內容")
    assert scorer.score(post) == "fallback verdict"


def test_gemini_quota_uses_fallback_for_qa(monkeypatch, tmp_path):
    fallback = FakeChat(factory=lambda _system, _messages: "browser fallback")
    chat = GeminiChat(
        api_key="test-key",
        model="gemini-test",
        daily_limit=10,
        requests_per_minute=60,
        state_path=str(tmp_path / "quota.json"),
        fallback=fallback,
    )
    monkeypatch.setattr(
        chat._client,
        "complete",
        lambda **_kwargs: (_ for _ in ()).throw(GeminiQuotaExhausted("quota")),
    )
    assert chat.complete(system="規則", messages=[{"role": "user", "content": "問題"}]).content == "browser fallback"

"""GeminiClient 的請求內容與回應處理（不連網：替換 session.post）。"""

from __future__ import annotations

import pytest

from reddit_tracker.config import get_settings
from reddit_tracker.llm import gemini
from reddit_tracker.llm.gemini import GeminiAPIError, GeminiClient


class _Resp:
    status_code = 200
    ok = True
    headers: dict = {}

    def __init__(self, data):
        self._data = data

    def json(self):
        return self._data


def _client(tmp_path, monkeypatch, data, *, thinking="low"):
    monkeypatch.setattr(get_settings(), "gemini_thinking_level", thinking)
    monkeypatch.setattr(gemini, "note_attempt", lambda **kw: None)
    client = GeminiClient(
        purpose="test", api_key="k", model="gemini-test", daily_limit=10,
        requests_per_minute=100, state_path=str(tmp_path / "q.json"),
    )
    sent = []

    def post(url, json, timeout):
        sent.append(json)
        return _Resp(data)

    client._session.post = post
    return client, sent


def _ok(text='{"a": 1}', finish="STOP", **usage):
    return {"candidates": [{"content": {"parts": [{"text": text}]}, "finishReason": finish}],
            "usageMetadata": usage}


SCHEMA = {"type": "object", "properties": {"a": {"type": "integer"}}, "required": ["a"]}


def _call(client, **kw):
    return client.complete(system="s", messages=[{"role": "user", "content": "u"}],
                           max_output_tokens=2000, temperature=0.2, **kw)


def test_schema_and_thinking_are_sent(tmp_path, monkeypatch):
    client, sent = _client(tmp_path, monkeypatch, _ok())
    _call(client, json_mode=True, json_schema=SCHEMA)
    cfg = sent[0]["generationConfig"]
    assert cfg["responseMimeType"] == "application/json"
    assert cfg["responseJsonSchema"] == SCHEMA
    assert cfg["thinkingConfig"] == {"thinkingLevel": "low"}


def test_no_schema_no_thinking(tmp_path, monkeypatch):
    client, sent = _client(tmp_path, monkeypatch, _ok("hi"), thinking="")
    _call(client)
    cfg = sent[0]["generationConfig"]
    assert "responseJsonSchema" not in cfg and "thinkingConfig" not in cfg and "responseMimeType" not in cfg


def test_output_tokens_include_thoughts(tmp_path, monkeypatch):
    client, _ = _client(tmp_path, monkeypatch, _ok(promptTokenCount=40, candidatesTokenCount=30, thoughtsTokenCount=12))
    result = _call(client, json_mode=True)
    assert (result.input_tokens, result.output_tokens) == (40, 42)


def test_truncated_output_raises(tmp_path, monkeypatch):
    client, _ = _client(tmp_path, monkeypatch, _ok('{"a": ', finish="MAX_TOKENS"))
    with pytest.raises(GeminiAPIError, match="MAX_TOKENS"):
        _call(client, json_mode=True)

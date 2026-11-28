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


# --- 準備前探測：不可用就整期用模板 ---

class _ErrResp(_Resp):
    def __init__(self, status, message):
        super().__init__({"error": {"code": status, "message": message}})
        self.status_code = status
        self.ok = False


def test_probe_reports_billing_error_without_touching_quota(tmp_path, monkeypatch):
    client, sent = _client(tmp_path, monkeypatch, None)
    client._session.post = lambda url, json, timeout: _ErrResp(402, "Your prepayment credits are depleted.")
    assert client.probe() == "HTTP 402: Your prepayment credits are depleted."
    assert client.guard.used("gemini-test") == 0


def test_probe_ok_and_network_error(tmp_path, monkeypatch):
    import requests

    client, sent = _client(tmp_path, monkeypatch, _ok("O", finish="MAX_TOKENS"))
    assert client.probe() is None
    assert sent[0]["generationConfig"] == {"maxOutputTokens": 1}

    def down(url, json, timeout):
        raise requests.ConnectionError("x")

    client._session.post = down
    assert client.probe() == "network error: ConnectionError"


def _settings(**kw):
    from types import SimpleNamespace

    return SimpleNamespace(**{"gemini_api_key": "k", "codex_bin": "/bin/sh", "gemini_daily_model": "m", **kw})


def test_unavailable_gemini_uses_template_not_codex(monkeypatch, caplog):
    from datetime import date

    from reddit_tracker.daily import run

    monkeypatch.setattr(run, "_gemini_unavailable", lambda s: "HTTP 402")
    monkeypatch.setattr(run.shutil, "which", lambda b: "/bin/sh")  # codex 在也不用
    assert run._resolve_writer_mode(_settings(), "gemini", date(2026, 11, 24)) == "template"
    assert "falls back to template" in caplog.text
    assert any(r.levelname == "ERROR" for r in caplog.records)


def test_available_gemini_is_kept_and_missing_key_skips_probe(monkeypatch):
    from datetime import date

    from reddit_tracker.daily import run

    calls = []
    monkeypatch.setattr(run, "_gemini_unavailable", lambda s: calls.append(s) or None)
    assert run._resolve_writer_mode(_settings(), "gemini", date(2026, 11, 24)) == "gemini"
    assert run._resolve_writer_mode(_settings(gemini_api_key=None), "gemini", date(2026, 11, 24)) == "template"
    assert run._resolve_writer_mode(_settings(), "codex", date(2026, 11, 24)) == "codex"
    assert len(calls) == 1


def test_served_model_version_is_recorded(tmp_path, monkeypatch):
    noted = []
    client, _ = _client(tmp_path, monkeypatch, {**_ok(), "modelVersion": "gemini-3.8-flash"})
    monkeypatch.setattr(gemini, "note_attempt", lambda **kw: noted.append(kw))
    _call(client, json_mode=True)
    assert noted[0]["model"] == "gemini-test" and noted[0]["model_version"] == "gemini-3.8-flash"

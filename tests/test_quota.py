"""依模型計數的 LLM 額度（手冊步驟 1、6.7）。"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from reddit_tracker.llm import gemini as gemini_module
from reddit_tracker.llm import quota as quota_module
from reddit_tracker.llm.gemini import GeminiClient, GeminiQuotaExhausted, GeminiQuotaGuard
from reddit_tracker.llm.quota import ModelQuotaGuard, QuotaExhausted


def test_count_is_keyed_by_model_and_shared_by_every_purpose(tmp_path):
    state = tmp_path / "q.json"
    a = ModelQuotaGuard(state_path=state, daily_limit=3)
    b = ModelQuotaGuard(state_path=state, daily_limit=3)  # 另一個 process 讀同一個 state 檔
    a.acquire(model="gpt-6.1-sol", purpose="daily")
    b.acquire(model="gpt-6.1-sol", purpose="reporter")
    a.acquire(model="gpt-6.1-sol", purpose="checker")
    with pytest.raises(QuotaExhausted):
        b.acquire(model="gpt-6.1-sol", purpose="daily")
    b.acquire(model="other-model", purpose="daily")  # 不同模型另外算

    data = json.loads(state.read_text(encoding="utf-8"))
    assert data["models"] == {"gpt-6.1-sol": 3, "other-model": 1}
    assert data["purposes"]["gpt-6.1-sol"] == {"daily": 1, "reporter": 1, "checker": 1}


def test_count_resets_on_new_pacific_day(tmp_path, monkeypatch):
    guard = ModelQuotaGuard(state_path=tmp_path / "q.json", daily_limit=1)
    monkeypatch.setattr(ModelQuotaGuard, "_day", staticmethod(lambda: "2026-10-28"))
    guard.acquire(model="m", purpose="daily")
    with pytest.raises(QuotaExhausted):
        guard.acquire(model="m", purpose="daily")
    monkeypatch.setattr(ModelQuotaGuard, "_day", staticmethod(lambda: "2026-10-29"))
    guard.acquire(model="m", purpose="daily")
    assert guard.used("m") == 1


def test_disabled_purpose_is_not_a_zero_limit(tmp_path):
    with pytest.raises(ValueError):
        ModelQuotaGuard(state_path=tmp_path / "q.json", daily_limit=0)


def test_rpm_limit_waits_instead_of_bursting(tmp_path, monkeypatch):
    clock = {"t": 1_000.0}
    sleeps = []
    monkeypatch.setattr(quota_module.time, "time", lambda: clock["t"])

    def sleep(seconds):
        sleeps.append(seconds)
        clock["t"] += seconds

    monkeypatch.setattr(quota_module.time, "sleep", sleep)
    guard = ModelQuotaGuard(state_path=tmp_path / "q.json", daily_limit=10, requests_per_minute=1)
    guard.acquire(model="m", purpose="daily")
    guard.acquire(model="m", purpose="daily")
    assert sleeps and sleeps[0] == pytest.approx(60.0)
    assert guard.used("m") == 2


def test_gemini_guard_counts_by_model(tmp_path):
    guard = GeminiQuotaGuard(state_path=str(tmp_path / "q.json"), daily_limit=1, requests_per_minute=5)
    guard.acquire(model="gemini-3.5-flash-lite", purpose="daily")
    with pytest.raises(GeminiQuotaExhausted):
        guard.acquire(model="gemini-3.5-flash-lite", purpose="scoring")
    guard.acquire(model="gemini-3.5-flash", purpose="qa")  # flash 另外算


class _Response:
    def __init__(self, status, body=None):
        self.status_code = status
        self.ok = 200 <= status < 300
        self.headers = {"Retry-After": "1"}
        self._body = body or {}

    def json(self):
        return self._body


def test_gemini_429_retries_once_and_every_attempt_consumes_quota(tmp_path, monkeypatch):
    settings = SimpleNamespace(
        gemini_api_key="k", gemini_daily_model="gemini-3.5-flash-lite", gemini_timeout_seconds=5,
        gemini_max_429_retries=1, gemini_requests_per_minute=100,
        llm_daily_limit=60, llm_quota_state_path=str(tmp_path / "q.json"),
    )
    monkeypatch.setattr(gemini_module, "get_settings", lambda: settings)
    monkeypatch.setattr(gemini_module.time, "sleep", lambda s: None)
    client = GeminiClient(purpose="daily")
    posts = []

    def post(url, json, timeout):
        posts.append(url)
        return _Response(429)

    monkeypatch.setattr(client._session, "post", post)
    kwargs = dict(system="s", messages=[{"role": "user", "content": "u"}], max_output_tokens=1, temperature=0)
    with pytest.raises(GeminiQuotaExhausted):
        client.complete(**kwargs)
    assert len(posts) == 2  # 1 次＋重試 1 次
    assert client.guard.used("gemini-3.5-flash-lite") == 2
    client.close()

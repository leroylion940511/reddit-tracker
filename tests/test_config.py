"""設定驗證：LLM provider 只允許 codex／gemini／template／fake，網頁備援已移除。"""

from __future__ import annotations

import importlib.util

import pytest
from pydantic import ValidationError

from reddit_tracker.config import LLM_PROVIDERS, Settings
from reddit_tracker.daily import run as run_module


def _settings(**values) -> Settings:
    return Settings(_env_file=None, **values)


def test_provider_whitelist_rejects_web():
    assert LLM_PROVIDERS == ("codex", "gemini", "template", "fake")
    for provider in LLM_PROVIDERS:
        assert _settings(daily_writer=provider).daily_writer == provider
    for bad in ("web", "WEB", "web_chat", "chatgpt-web", "anthropic"):
        with pytest.raises(ValidationError):
            _settings(daily_writer=bad)


def test_web_provider_from_environment_is_rejected(monkeypatch):
    monkeypatch.setenv("DAILY_WRITER", "web")
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_legacy_web_keys_are_ignored_and_no_web_module_remains(monkeypatch):
    # 舊 .env 若還留著 LLM_PROVIDER=web／GEMINI_FALLBACK_PROVIDER=web，沒有任何程式讀它們。
    monkeypatch.setenv("LLM_PROVIDER", "web")
    monkeypatch.setenv("GEMINI_FALLBACK_PROVIDER", "web")
    settings = Settings(_env_file=None)
    assert not hasattr(settings, "llm_provider")
    assert not hasattr(settings, "gemini_fallback_provider")
    assert importlib.util.find_spec("reddit_tracker.llm.web_chat") is None


def test_prepare_rejects_unknown_writer_modes():
    with pytest.raises(ValueError, match="web"):
        run_module.prepare_daily(run_module.date(2026, 10, 28), writer_mode="web")


def test_step1_defaults_match_handbook():
    settings = _settings()
    assert settings.legacy_jobs_enabled is False
    assert settings.llm_daily_limit == 60
    assert settings.gemini_max_429_retries == 1
    assert settings.codex_max_retries == 1
    assert run_module.WRITE_ATTEMPTS == 2


def test_env_example_has_no_web_provider():
    from pathlib import Path

    text = (Path(__file__).resolve().parents[1] / ".env.example").read_text(encoding="utf-8")
    assert "LLM_PROVIDER" not in text and "=web" not in text
    assert "LLM_DAILY_LIMIT=60" in text and "GEMINI_MAX_429_RETRIES=1" in text
    assert "LEGACY_JOBS_ENABLED=false" in text

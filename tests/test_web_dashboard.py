from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from reddit_tracker import web


def test_dashboard_and_static_assets_are_served():
    client = TestClient(web.app)

    response = client.get("/")
    css = client.get("/static/dashboard.css")

    assert response.status_code == 200
    assert "Reddit Tracker 控制台" in response.text
    assert css.status_code == 200


def test_candidates_endpoint_serializes_the_metadata_column():
    client = TestClient(web.app)

    response = client.get("/api/data/candidates?limit=1")

    assert response.status_code == 200
    if response.json():
        assert "metadata" in response.json()[0]


def test_update_env_only_changes_allowlisted_settings(tmp_path: Path, monkeypatch):
    env_path = tmp_path / ".env"
    env_path.write_text("TELEGRAM_BOT_TOKEN=secret\nLLM_PROVIDER=web\n", encoding="utf-8")
    monkeypatch.setattr(web, "ENV_PATH", env_path)

    web.update_env({"scoring_minutes": 45, "llm_provider": "fake"})

    content = env_path.read_text(encoding="utf-8")
    assert "TELEGRAM_BOT_TOKEN=secret" in content
    assert "LLM_PROVIDER=fake" in content
    assert "SCORING_MINUTES=45" in content


@pytest.mark.parametrize(
    ("key", "value", "message"),
    [
        ("web_llm_cdp_url", "http://example.com:9222", "127.0.0.1"),
        ("scoring_batch_limit", 999, "1 到 200"),
        ("telegram_bot_token", "not-allowed", "不允許修改"),
    ],
)
def test_setting_validation_rejects_unsafe_or_invalid_values(key, value, message):
    with pytest.raises(ValueError, match=message):
        web._validate_setting(key, value)


def test_stop_service_disables_even_when_not_loaded(monkeypatch):
    calls: list[list[str]] = []

    class Result:
        def __init__(self, returncode: int):
            self.returncode = returncode
            self.stdout = ""
            self.stderr = ""

    def fake_run(command, **_kwargs):
        calls.append(command)
        return Result(1 if "bootout" in command else 0)

    monkeypatch.setattr(web, "_run", fake_run)

    result = web._stop_service("com.leroy.reddit-tracker.bot")

    assert result["result"] == "already_stopped"
    assert calls[1][1] == "disable"

from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from reddit_tracker import web
from reddit_tracker.models import Base, CandidatePost, EditionItem, EditionItemSource, SubredditSource
from reddit_tracker.newsroom.repository import create_reader_profile, get_or_create_edition


def test_dashboard_and_static_assets_are_served():
    client = TestClient(web.app)

    response = client.get("/")
    css = client.get("/static/dashboard.css")

    assert response.status_code == 200
    assert "Reddit Tracker 控制台" in response.text
    assert "啟動新聞室" in response.text
    assert "候選來源健康" in response.text
    assert "回饋通路" in response.text
    assert "啟動專案" not in response.text
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


def test_service_status_recognizes_launchctl_symbolic_disabled_value(monkeypatch):
    class Result:
        def __init__(self, returncode: int, stdout: str = "", stderr: str = ""):
            self.returncode = returncode
            self.stdout = stdout
            self.stderr = stderr

    label = "com.leroy.reddit-tracker.bot"

    def fake_run(command, **_kwargs):
        if command[1] == "print-disabled":
            return Result(0, f'{{\n    "{label}" => disabled\n}}')
        return Result(1, stderr="service not loaded")

    monkeypatch.setattr(web, "_run", fake_run)

    status = web._service_status(label)

    assert status["running"] is False
    assert status["disabled"] is True


def test_newsroom_start_refuses_schema_that_has_not_been_deployed(monkeypatch):
    monkeypatch.setattr(web, "_service_status", lambda _label: {"running": False, "schema_ready": False})

    with pytest.raises(RuntimeError, match="newsroom-deploy"):
        web._start_service("com.leroy.reddit-tracker.newsroom")


def test_newsroom_endpoints_show_safe_edition_artifacts_and_record_feedback(tmp_path: Path, monkeypatch):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'newsroom-web.db'}",
        future=True,
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    session = Session()
    reader = create_reader_profile(
        session,
        telegram_chat_id=100,
        preference_prompt="多看台灣生活。",
    )
    now = datetime.now(UTC)
    edition = get_or_create_edition(
        session,
        reader=reader,
        edition_date=date(2026, 9, 18),
        window_start=now - timedelta(days=1),
        window_end=now,
    ).edition
    edition.status = "drafted"
    item = EditionItem(
        edition_id=edition.id,
        kind="brief",
        position=1,
        status="drafted",
        headline_zh="一則可閱讀的 Reddit 討論",
        body_zh="這是以來源為主的繁中摘要。",
        why_it_matters="讓讀者判斷是否想多看這類主題。",
        confidence="low",
        warnings=[],
    )
    source = SubredditSource(name="taiwan", lang_hint="zh", enabled=True, last_polled_at=now)
    candidate = CandidatePost(
        reddit_post_id="source-health-1",
        subreddit="taiwan",
        title="候選來源健康測試",
        selftext="來源資料可被控制台安全摘要。",
        permalink="/r/taiwan/comments/source-health-1/test/",
        discovered_at=now,
    )
    session.add_all([item, source, candidate])
    session.commit()

    @contextmanager
    def test_scope():
        scoped = Session()
        try:
            yield scoped
            scoped.commit()
        except Exception:
            scoped.rollback()
            raise
        finally:
            scoped.close()

    monkeypatch.setattr(web, "session_scope", test_scope)
    client = TestClient(web.app)

    listed = client.get("/api/newsroom/editions")
    detail = client.get(f"/api/newsroom/editions/{edition.id}")
    pilot = client.get("/api/newsroom/pilot")
    source_health = client.get("/api/newsroom/source-health")
    profile = client.get("/api/newsroom/reader-profile")
    saved_profile = client.put(
        "/api/newsroom/reader-profile",
        json={
            "preference_prompt": "多看台灣生活，少看政治。",
            "included_topics": ["taiwan_life", " taiwan_life "],
            "excluded_topics": ["politics"],
            "included_subreddits": ["taiwan"],
            "excluded_subreddits": ["worldnews"],
            "included_keywords": ["local food", " local food "],
            "excluded_keywords": ["spoiler"],
        },
    )
    first = client.post(f"/api/newsroom/items/{item.id}/feedback", json={"action": "more"})
    repeat = client.post(f"/api/newsroom/items/{item.id}/feedback", json={"action": "more"})

    assert listed.status_code == 200
    assert listed.json()[0]["item_count"] == 1
    assert detail.status_code == 200
    assert detail.json()["view"]["items"][0]["id"] == item.id
    assert pilot.status_code == 200
    assert len(pilot.json()["days"]) == 7
    assert source_health.json()["enabled_source_count"] == 1
    assert source_health.json()["current_source_count"] == 1
    assert source_health.json()["sources"][0]["recent_candidate_count"] == 1
    assert profile.json()["delivery_time"] == "08:30"
    assert saved_profile.json()["included_topics"] == ["taiwan_life"]
    assert saved_profile.json()["included_keywords"] == ["local food"]
    assert saved_profile.json()["excluded_keywords"] == ["spoiler"]
    assert first.json()["duplicate"] is False
    assert repeat.json()["duplicate"] is True
    session.close()
    engine.dispose()


def test_newsroom_pilot_gate_remains_passed_after_its_original_week(session, monkeypatch):
    reader = create_reader_profile(session, telegram_chat_id=100, preference_prompt="多看台灣生活。")
    candidate = CandidatePost(
        reddit_post_id="pilot-source",
        subreddit="taiwan",
        title="試刊來源",
        selftext="可追溯的候選資料。",
        permalink="/r/taiwan/comments/pilot-source/test/",
    )
    session.add(candidate)
    session.flush()
    for offset in range(7):
        edition_date = date(2026, 9, 19) + timedelta(days=offset)
        edition = get_or_create_edition(
            session,
            reader=reader,
            edition_date=edition_date,
            window_start=datetime.combine(edition_date - timedelta(days=1), datetime.min.time(), tzinfo=UTC),
            window_end=datetime.combine(edition_date, datetime.min.time(), tzinfo=UTC),
        ).edition
        edition.status = "published"
        for position in range(1, 9):
            session.add(EditionItem(
                edition_id=edition.id,
                kind="brief",
                position=position,
                status="published",
                headline_zh=f"試刊項目 {position}",
                body_zh="來源完整的繁中摘要。",
                why_it_matters="驗證七日 gate。",
                confidence="medium",
                warnings=[],
            ))
        session.flush()
        items = session.scalars(select(EditionItem).where(EditionItem.edition_id == edition.id)).all()
        session.add_all(EditionItemSource(edition_item_id=item.id, candidate_post_id=candidate.id) for item in items)
    session.commit()

    @contextmanager
    def test_scope():
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise

    monkeypatch.setattr(web, "session_scope", test_scope)
    report = web._newsroom_pilot(now=datetime(2026, 9, 26, 9, tzinfo=UTC))

    assert report["pilot_complete"] is True
    assert report["current_window_complete"] is False
    assert report["gate_passed_window"] == {
        "start_date": "2026-09-19",
        "end_date": "2026-09-25",
    }

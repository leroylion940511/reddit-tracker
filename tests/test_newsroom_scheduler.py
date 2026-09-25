"""v5 scheduler owns candidate intake without reviving v4 delivery jobs."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from reddit_tracker.newsroom import scheduler


def test_build_scheduler_registers_discovery_prepare_and_only_newsroom_delivery(monkeypatch):
    settings = SimpleNamespace(
        newsroom_delivery_timezone="Asia/Taipei",
        newsroom_preparation_hour=5,
        newsroom_preparation_minute=30,
        newsroom_delivery_hour=8,
        newsroom_delivery_minute=30,
        newsroom_discovery_interval_minutes=90,
    )
    monkeypatch.setattr(scheduler, "get_settings", lambda: settings)

    built = scheduler.build_scheduler()

    jobs = {job.id: job for job in built.get_jobs()}
    assert set(jobs) == {"newsroom_candidate_discovery", "newsroom_prepare_edition", "newsroom_daily_edition"}
    assert jobs["newsroom_candidate_discovery"].trigger.interval.total_seconds() == 90 * 60
    built.start(paused=True)
    assert jobs["newsroom_candidate_discovery"].next_run_time is not None
    assert jobs["newsroom_candidate_discovery"].next_run_time <= datetime.now(ZoneInfo("Asia/Taipei")) + timedelta(seconds=1)
    built.shutdown()
    assert "hour='5'" in str(jobs["newsroom_prepare_edition"].trigger)
    assert "minute='30'" in str(jobs["newsroom_prepare_edition"].trigger)


def test_candidate_discovery_uses_existing_source_intake_and_closes_scraper(monkeypatch):
    events: list[object] = []
    scraper = SimpleNamespace(close=lambda: events.append("closed"))
    settings = SimpleNamespace(discovery_per_sub_limit=30)

    @contextmanager
    def fake_scope():
        events.append("scope_open")
        yield object()
        events.append("scope_closed")

    def discover(session, scraper_arg, *, per_sub_limit, commit_each_source):
        events.append((session, scraper_arg, per_sub_limit, commit_each_source))
        return [SimpleNamespace(inserted=2, skipped_dupe=5)]

    monkeypatch.setattr(scheduler, "get_settings", lambda: settings)
    monkeypatch.setattr(scheduler, "build_scraper", lambda: scraper)
    monkeypatch.setattr(scheduler, "session_scope", fake_scope)
    monkeypatch.setattr(scheduler, "discover_from_subreddits", discover)

    scheduler._run_candidate_discovery()

    assert events[0] == "scope_open"
    assert events[1][1:] == (scraper, 30, True)
    assert events[-2:] == ["scope_closed", "closed"]


def test_prepare_today_builds_a_draft_without_publishing(monkeypatch):
    settings = SimpleNamespace(newsroom_delivery_timezone="Asia/Taipei")
    calls: list[object] = []
    prepared = SimpleNamespace(edition_id=4, view=SimpleNamespace(items=[object()] * 8), writer_used="gemini")

    monkeypatch.setattr(scheduler, "get_settings", lambda: settings)
    monkeypatch.setattr(
        scheduler,
        "prepare_edition",
        lambda *, edition_date: calls.append(edition_date) or prepared,
    )

    scheduler._prepare_today()

    assert calls == [datetime.now(ZoneInfo("Asia/Taipei")).date()]

"""Scheduler registers only collection and v2.0 daily jobs; legacy jobs never come back."""

from __future__ import annotations

import logging

from datetime import datetime, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from reddit_tracker.newsroom import scheduler


def _settings(**overrides):
    values = dict(
        newsroom_delivery_timezone="Asia/Taipei",
        news_collection_enabled=True,
        news_collection_tick_minutes=15,
        daily_edition_enabled=True,
        daily_prepare_hour=6,
        daily_prepare_minute=0,
        daily_delivery_hour=8,
        daily_delivery_minute=35,
        legacy_jobs_enabled=False,
    )
    values.update(overrides)
    return SimpleNamespace(**values)


def test_build_scheduler_registers_collection_and_daily_jobs(monkeypatch):
    monkeypatch.setattr(scheduler, "get_settings", lambda: _settings())

    built = scheduler.build_scheduler()

    jobs = {job.id: job for job in built.get_jobs()}
    assert set(jobs) == {"newsroom_source_collection", "daily_prepare_edition", "daily_publish_edition"}
    assert jobs["newsroom_source_collection"].trigger.interval.total_seconds() == 15 * 60
    built.start(paused=True)
    assert jobs["newsroom_source_collection"].next_run_time <= datetime.now(ZoneInfo("Asia/Taipei")) + timedelta(seconds=1)
    built.shutdown()
    assert "hour='6'" in str(jobs["daily_prepare_edition"].trigger)
    assert "minute='35'" in str(jobs["daily_publish_edition"].trigger)


EXPECTED_JOBS = {"newsroom_source_collection", "daily_prepare_edition", "daily_publish_edition"}


def test_legacy_job_names_are_the_three_from_the_handbook():
    assert scheduler.LEGACY_JOB_IDS == {
        "newsroom_candidate_discovery", "newsroom_prepare_edition", "newsroom_daily_edition",
    }
    assert not scheduler.LEGACY_JOB_IDS & EXPECTED_JOBS


def test_legacy_jobs_disabled_by_default_registers_no_legacy_job(monkeypatch):
    monkeypatch.setattr(scheduler, "get_settings", lambda: _settings())
    ids = {job.id for job in scheduler.build_scheduler().get_jobs()}
    assert ids == EXPECTED_JOBS
    assert not ids & scheduler.LEGACY_JOB_IDS


def test_legacy_jobs_enabled_still_does_not_resurrect_removed_code(monkeypatch, caplog):
    monkeypatch.setattr(scheduler, "get_settings", lambda: _settings(legacy_jobs_enabled=True))
    with caplog.at_level(logging.WARNING, logger=scheduler.__name__):
        ids = {job.id for job in scheduler.build_scheduler().get_jobs()}
    assert ids == EXPECTED_JOBS
    assert "removed in commit 2d95c07" in caplog.text


def test_settings_default_has_legacy_jobs_off():
    from reddit_tracker.config import Settings

    assert Settings(_env_file=None).legacy_jobs_enabled is False


def test_build_scheduler_respects_disabled_flags(monkeypatch):
    monkeypatch.setattr(
        scheduler, "get_settings",
        lambda: _settings(news_collection_enabled=False, daily_edition_enabled=False),
    )

    assert scheduler.build_scheduler().get_jobs() == []


def test_daily_jobs_use_delivery_timezone_date(monkeypatch):
    calls: list[tuple[str, object]] = []
    monkeypatch.setattr(scheduler, "get_settings", lambda: _settings())
    monkeypatch.setattr(scheduler, "prepare_daily", lambda day: calls.append(("prepare", day)) or 1)
    monkeypatch.setattr(scheduler, "publish_daily", lambda day: calls.append(("publish", day)) or 1)

    scheduler._prepare_daily_today()
    scheduler._publish_daily_today()

    today = datetime.now(ZoneInfo("Asia/Taipei")).date()
    assert calls == [("prepare", today), ("publish", today)]

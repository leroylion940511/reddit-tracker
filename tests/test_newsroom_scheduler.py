"""Scheduler registers only collection and v2.0 daily jobs; legacy jobs never come back."""

from __future__ import annotations

import logging

import pytest
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
        daily_startup_catchup_minutes=0,
        db_backup_dir="",
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


# ── 06:00 準備期間收集讓開（11/24–11/26 撞鎖）──────────────────────────────


def test_collection_tick_during_prepare_is_deferred_and_caught_up_after(monkeypatch):
    events: list[str] = []
    monkeypatch.setattr(scheduler, "_collect_and_cluster", lambda: events.append("collect"))

    def fake_prepare():
        events.append("prepare-start")
        scheduler._run_source_collection()  # tick 落在準備期間
        events.append("prepare-end")

    monkeypatch.setattr(scheduler, "_prepare_daily_today_inner", fake_prepare)
    scheduler._prepare_daily_today()

    assert events == ["prepare-start", "prepare-end", "collect"]
    assert not scheduler._PREPARING.is_set()
    scheduler._run_source_collection()  # 之後的 tick 照常
    assert events[-1] == "collect"


def test_failed_prepare_still_releases_collection_and_catches_up(monkeypatch):
    events: list[str] = []
    monkeypatch.setattr(scheduler, "_collect_and_cluster", lambda: events.append("collect"))

    def failing_prepare():
        scheduler._run_source_collection()
        raise RuntimeError("codex down")

    monkeypatch.setattr(scheduler, "_prepare_daily_today_inner", failing_prepare)
    try:
        scheduler._prepare_daily_today()
    except RuntimeError:
        pass
    assert events == ["collect"]
    assert not scheduler._PREPARING.is_set()


def test_prepare_waits_for_running_collection_to_finish(monkeypatch):
    import threading

    events: list[str] = []
    started, release = threading.Event(), threading.Event()

    def slow_collect():
        started.set()
        release.wait(5)
        events.append("collect-done")

    monkeypatch.setattr(scheduler, "_collect_and_cluster", slow_collect)
    monkeypatch.setattr(scheduler, "_prepare_daily_today_inner", lambda: events.append("prepare"))
    worker = threading.Thread(target=scheduler._run_source_collection)
    worker.start()
    started.wait(5)
    preparer = threading.Thread(target=scheduler._prepare_daily_today)
    preparer.start()
    release.set()
    worker.join(5)
    preparer.join(5)
    assert events == ["collect-done", "prepare"]


def test_overlapping_collection_rounds_do_not_run_twice(monkeypatch):
    scheduler._COLLECTION_LOCK.acquire()
    calls = []
    monkeypatch.setattr(scheduler, "_collect_and_cluster", lambda: calls.append(1))
    try:
        scheduler._run_source_collection()
    finally:
        scheduler._COLLECTION_LOCK.release()
    assert calls == []


# ── 冷啟動補做準備／發行 ─────────────────────────────────────────────────


TPE = ZoneInfo("Asia/Taipei")


def _catchup_env(monkeypatch, session_factory, status, *, minutes=180):
    from contextlib import contextmanager

    from reddit_tracker.models import DailyEdition

    with session_factory() as s:
        if status is not None:
            ts = datetime(2026, 11, 25, 22, tzinfo=ZoneInfo("UTC"))
            s.add(DailyEdition(
                edition_date=datetime(2026, 11, 26).date(), status=status,
                window_start=ts, prepared_at=ts, created_at=ts, updated_at=ts,
            ))
            s.commit()

    @contextmanager
    def scope():
        s = session_factory()
        try:
            yield s
            s.commit()
        finally:
            s.close()

    calls: list[str] = []
    monkeypatch.setattr(scheduler, "get_settings", lambda: _settings(daily_startup_catchup_minutes=minutes))
    monkeypatch.setattr(scheduler, "session_scope", scope)
    monkeypatch.setattr(scheduler, "_prepare_daily_today", lambda: calls.append("prepare"))
    monkeypatch.setattr(scheduler, "_publish_daily_today", lambda: calls.append("publish"))
    return calls


@pytest.fixture()
def session_factory(engine):
    from sqlalchemy.orm import sessionmaker

    return sessionmaker(bind=engine, expire_on_commit=False)


@pytest.mark.parametrize(
    ("status", "clock", "expected", "calls"),
    [
        ("drafted", (8, 40), "published", ["publish"]),       # 08:34 關機、08:40 啟動
        ("drafted", (8, 20), "none", []),                     # 還沒到發行時刻：交給 08:35 的 cron
        ("drafted", (11, 36), "none", []),                    # 超過補發時段
        ("published", (8, 40), "none", []),
        ("delivery_failed", (8, 40), "needs_check", []),      # 不確定送達，不自動重送
        ("publishing", (9, 0), "needs_check", []),
        (None, (6, 30), "prepared", ["prepare"]),             # 06:00 前關機、06:30 啟動
        (None, (5, 50), "none", []),
        (None, (8, 40), "none", []),                          # 過了發行時刻沒有版次：不補編
    ],
)
def test_startup_catchup(monkeypatch, session_factory, status, clock, expected, calls):
    recorded = _catchup_env(monkeypatch, session_factory, status)
    now = datetime(2026, 11, 26, *clock, tzinfo=TPE)
    assert scheduler.startup_catchup(now) == expected
    assert recorded == calls


def test_startup_catchup_off_by_default(monkeypatch, session_factory):
    recorded = _catchup_env(monkeypatch, session_factory, "drafted", minutes=0)
    assert scheduler.startup_catchup(datetime(2026, 11, 26, 8, 40, tzinfo=TPE)) == "off"
    assert recorded == []
    ids = {job.id for job in scheduler.build_scheduler().get_jobs()}
    assert ids == EXPECTED_JOBS


def test_optional_jobs_registered_when_configured(monkeypatch):
    monkeypatch.setattr(
        scheduler, "get_settings",
        lambda: _settings(daily_startup_catchup_minutes=180, db_backup_dir="/tmp/x", db_backup_hour=9, db_backup_minute=30),
    )
    jobs = {job.id: job for job in scheduler.build_scheduler().get_jobs()}
    assert set(jobs) == EXPECTED_JOBS | {"db_backup", "daily_startup_catchup"}
    assert "minute='30'" in str(jobs["db_backup"].trigger)

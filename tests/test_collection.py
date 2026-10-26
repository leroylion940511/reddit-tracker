"""Multi-source collection: normalization, dedup, due logic, health records, report."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from reddit_tracker.collection import collector
from reddit_tracker.collection.collector import (
    FetchedEntry,
    FetchOutcome,
    collect_due_sources,
)
from reddit_tracker.collection.normalize import (
    canonicalize_url,
    clean_summary,
    resolve_published_at,
    title_fingerprint,
)
from reddit_tracker.collection.report import build_collection_report
from reddit_tracker.models import SourceFetchRun, SourceItem
from reddit_tracker.newsroom import scheduler
from reddit_tracker.seeds.news_sources import SourceRegistry

NOW = datetime(2026, 10, 27, 2, 0, tzinfo=timezone.utc)


def _registry(*sources):
    return SourceRegistry(
        version=1,
        sections={"taiwan": "台灣", "world": "國際", "social": "社群觀察"},
        sources=list(sources),
    )


def _src(source_id, **overrides):
    base = dict(id=source_id, name=source_id, section="taiwan", tier="T2", method="rss",
                url=f"https://example.com/{source_id}.xml", lang="zh-Hant")
    return base | overrides


def _ok(*entries, started_at=NOW):
    return FetchOutcome(started_at=started_at, ok=True, http_status=200, entries=list(entries))


# ── normalize ────────────────────────────────────────────────────────────


def test_canonicalize_url_strips_tracking_www_fragment_and_trailing_slash():
    assert (
        canonicalize_url("HTTPS://www.Example.com/news/1/?utm_source=x&b=2&a=1&fbclid=z#top")
        == "https://example.com/news/1?a=1&b=2"
    )


def test_title_fingerprint_ignores_punctuation_and_width_but_skips_short_titles():
    assert title_fingerprint("賴清德：今日 出訪！") == title_fingerprint("賴清德 今日出訪")
    assert title_fingerprint("ＡＢＣ news today") == title_fingerprint("abc News Today")
    assert title_fingerprint("直播更新") is None
    assert title_fingerprint(None) is None


@pytest.mark.parametrize(
    ("parsed", "offset", "expected", "estimated"),
    [
        (NOW - timedelta(hours=2), 0, NOW - timedelta(hours=2), False),
        (None, 0, NOW, True),
        (datetime(1970, 1, 1, tzinfo=timezone.utc), 0, NOW, True),
        (NOW + timedelta(hours=3), 0, NOW, True),
        (NOW + timedelta(hours=7), -8, NOW - timedelta(hours=1), False),
    ],
)
def test_resolve_published_at(parsed, offset, expected, estimated):
    assert resolve_published_at(parsed, NOW, offset) == (expected, estimated)


def test_clean_summary_strips_html_and_truncates():
    assert clean_summary("<p>台北&amp;新北</p>\n<b>交通</b>") == "台北&新北 交通"
    assert len(clean_summary("字" * 5000)) == 1000
    assert clean_summary(None) is None


# ── collect ──────────────────────────────────────────────────────────────


def test_collect_stores_items_and_marks_cross_source_duplicates(session):
    registry = _registry(_src("a"), _src("b"), _src("c", section="world"))
    outcomes = {
        "a": _ok(FetchedEntry(url="https://news.tw/1?utm_source=rss", guid="a-1", title="行政院通過明年度總預算案"),
                 FetchedEntry(url="https://news.tw/2", guid="a-2", title="颱風明天登陸東部地區")),
        "b": _ok(FetchedEntry(url="https://www.news.tw/1/", guid="b-1", title="不同標題但同一網址的報導")),
        "c": _ok(FetchedEntry(url="https://other.tw/x", guid="c-1", title="颱風明天登陸東部地區！")),
    }

    stats = collect_due_sources(session, registry, now=NOW, fetcher=lambda s, prev: outcomes[s.id])

    assert {s.source_id: (s.new, s.duplicate) for s in stats} == {"a": (2, 0), "b": (1, 1), "c": (1, 1)}
    items = {i.item_key: i for i in session.scalars(select(SourceItem))}
    roots = [i for i in items.values() if i.duplicate_of_id is None]
    assert len(roots) == 2
    world = session.scalar(select(SourceItem).where(SourceItem.source_id == "c"))
    assert world.section == "world"
    assert session.get(SourceItem, world.duplicate_of_id).title == "颱風明天登陸東部地區"


def test_collect_skips_items_already_seen_from_same_source(session):
    registry = _registry(_src("a"))
    entry = FetchedEntry(url="https://news.tw/1", guid="a-1", title="同一篇報導再次出現在 feed")
    collect_due_sources(session, registry, now=NOW, fetcher=lambda s, p: _ok(entry))
    stats = collect_due_sources(session, registry, now=NOW + timedelta(hours=2), fetcher=lambda s, p: _ok(entry))
    assert stats[0].new == 0
    assert session.query(SourceItem).count() == 1


def test_collect_only_fetches_due_enabled_feed_sources(session):
    registry = _registry(
        _src("hourly"),
        _src("daily", interval_min=1440),
        _src("off", enabled=False, notes="停用"),
        _src("reddit", method="reddit", url="taiwan", section="social", tier="T4"),
    )
    fetched: list[str] = []

    def fetcher(source, previous):
        fetched.append(source.id)
        return _ok()

    collect_due_sources(session, registry, now=NOW, fetcher=fetcher)
    assert sorted(fetched) == ["daily", "hourly"]

    fetched.clear()
    collect_due_sources(session, registry, now=NOW + timedelta(minutes=61), fetcher=fetcher)
    assert fetched == ["hourly"]

    fetched.clear()
    collect_due_sources(session, registry, now=NOW + timedelta(minutes=62), force=True, fetcher=fetcher)
    assert sorted(fetched) == ["daily", "hourly"]


def test_failed_fetch_is_recorded_and_previous_run_is_passed_to_fetcher(session):
    registry = _registry(_src("a"))
    collect_due_sources(
        session, registry, now=NOW,
        fetcher=lambda s, p: FetchOutcome(started_at=NOW, ok=False, http_status=503, error="HTTPError: 503"),
    )
    seen = {}

    def fetcher(source, previous):
        seen["previous"] = previous
        return _ok()

    collect_due_sources(session, registry, now=NOW + timedelta(hours=2), fetcher=fetcher)
    runs = session.scalars(select(SourceFetchRun).order_by(SourceFetchRun.id)).all()
    assert [r.ok for r in runs] == [False, True]
    assert seen["previous"].error == "HTTPError: 503"


def test_store_failure_is_logged_as_failed_run(session, monkeypatch):
    registry = _registry(_src("a"))

    def boom(*args, **kwargs):
        raise RuntimeError("disk full")

    monkeypatch.setattr(collector, "_duplicate_root", boom)
    stats = collect_due_sources(
        session, registry, now=NOW,
        fetcher=lambda s, p: _ok(FetchedEntry(url="https://n.tw/1", title="會在寫入時失敗的項目")),
    )
    assert not stats[0].ok
    run = session.scalar(select(SourceFetchRun))
    assert run.ok is False and "disk full" in run.error
    assert session.query(SourceItem).count() == 0


def test_fetch_source_sends_conditional_headers_and_redacts_key(monkeypatch):
    calls = {}

    class Resp:
        status_code = 304
        headers: dict = {}

    def fake_get(url, headers, timeout):
        calls.update(url=url, headers=headers, timeout=timeout)
        return Resp()

    monkeypatch.setattr(collector.requests, "get", fake_get)
    monkeypatch.setattr(
        collector, "get_settings",
        lambda: SimpleNamespace(rsshub_base_url="http://127.0.0.1:1200", rsshub_access_key="abc123"),
    )
    source = SourceRegistry.model_validate(
        {"version": 1, "sections": {"taiwan": "台灣"}, "sources": [_src("hub", method="rsshub", url="/cna/aipl")]}
    ).sources[0]
    previous = SourceFetchRun(ok=True, etag='"v1"', last_modified="Mon, 26 Oct 2026 00:00:00 GMT")

    outcome = collector.fetch_source(source, previous)

    assert outcome.ok and outcome.not_modified and outcome.etag == '"v1"'
    assert calls["headers"]["If-None-Match"] == '"v1"'
    assert calls["timeout"] == 90.0

    def failing_get(url, headers, timeout):
        raise collector.requests.ConnectionError(f"failed for {url}")

    monkeypatch.setattr(collector.requests, "get", failing_get)
    failed = collector.fetch_source(source, None)
    assert not failed.ok and "abc123" not in failed.error and "key=***" in failed.error


# ── report ───────────────────────────────────────────────────────────────


def test_report_counts_unique_items_per_section_day_and_source_health(session):
    registry = _registry(_src("a"), _src("b"), _src("c", section="world"))
    outcomes = {
        "a": _ok(FetchedEntry(url="https://n.tw/1", guid="1", title="第一則台灣新聞的完整標題")),
        "b": _ok(FetchedEntry(url="https://n.tw/1", guid="2", title="同網址的轉載稿件標題不同")),
        "c": FetchOutcome(started_at=NOW, ok=False, http_status=503, error="HTTPError: 503 | upstream"),
    }
    collect_due_sources(session, registry, now=NOW, fetcher=lambda s, p: outcomes[s.id])

    report = build_collection_report(session, registry, days=2, now=NOW)

    assert "| 台灣 | 0 | 1 | 1 |" in report
    assert "| **其中重複** | 0 | 1 | 1 |" in report
    assert "| `c` | 國際 | 1 | 0% | — | 1 | 0 | HTTPError: 503 / upstream |" in report


# ── scheduler ────────────────────────────────────────────────────────────


def _scheduler_settings(enabled):
    return SimpleNamespace(
        newsroom_delivery_timezone="Asia/Taipei",
        news_collection_enabled=enabled,
        news_collection_tick_minutes=15,
    )


@pytest.mark.parametrize("enabled", [False, True])
def test_source_collection_job_is_registered_only_when_enabled(monkeypatch, enabled):
    monkeypatch.setattr(scheduler, "get_settings", lambda: _scheduler_settings(enabled))
    built = scheduler.build_scheduler()
    jobs = {job.id: job for job in built.get_jobs()}
    assert ("newsroom_source_collection" in jobs) is enabled
    if enabled:
        assert jobs["newsroom_source_collection"].trigger.interval.total_seconds() == 15 * 60


def test_same_title_far_apart_in_time_is_not_a_duplicate(session):
    registry = _registry(_src("cbc"))
    title = "中央銀行重要人事異動公告說明"
    outcome = _ok(
        FetchedEntry(url="https://cbc.gov.tw/1", guid="1", title=title, published=NOW - timedelta(days=200)),
        FetchedEntry(url="https://cbc.gov.tw/2", guid="2", title=title, published=NOW - timedelta(days=1)),
        FetchedEntry(url="https://cbc.gov.tw/3", guid="3", title=title, published=NOW - timedelta(hours=2)),
    )
    stats = collect_due_sources(session, registry, now=NOW, fetcher=lambda s, p: outcome)
    assert (stats[0].new, stats[0].duplicate) == (3, 1)

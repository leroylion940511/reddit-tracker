"""SCHEDULE.md M5.2 — tiered polling (tier_for_age / select_due / capture)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from reddit_tracker.models import CandidatePost, PostSnapshot, TrackedPost
from reddit_tracker.scrapers.base import PostPayload
from reddit_tracker.scrapers.fake import FakeScraper
from reddit_tracker.services.polling import (
    ACTIVE_STATUS,
    ARCHIVED_STATUS,
    TIER_ARCHIVE,
    TIER_COOLING,
    TIER_HOT,
    capture_snapshot,
    interval_minutes_for_tier,
    run_polling,
    select_due_posts,
    tier_for_age,
)


NOW = datetime(2026, 5, 23, 12, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _make_payload(rid: str, *, score: int = 100, num_comments: int = 10, upvote: float = 0.92) -> PostPayload:
    return PostPayload(
        reddit_post_id=rid,
        subreddit="Taiwan",
        title="hello",
        selftext="x" * 100,
        author="alice",
        author_karma=500,
        score=score,
        upvote_ratio=upvote,
        num_comments=num_comments,
        created_utc=NOW - timedelta(hours=8),
        permalink=f"/r/Taiwan/comments/{rid}/x/",
        url=f"https://www.reddit.com/r/Taiwan/comments/{rid}/x/",
        is_self=True,
        is_deleted=False,
        over_18=False,
        stickied=False,
    )


def _persist_tracked(
    session,
    *,
    rid: str = "p1",
    posted_hours_ago: float = 8.0,
    tier: str = TIER_HOT,
    last_polled_at: datetime | None = None,
    status: str = ACTIVE_STATUS,
    user_id: int = 1,
) -> TrackedPost:
    c = CandidatePost(
        reddit_post_id=rid,
        subreddit="Taiwan",
        title="t",
        selftext="x" * 100,
        permalink=f"/r/Taiwan/comments/{rid}/x/",
        author_username="alice",
        posted_at=NOW - timedelta(hours=posted_hours_ago),
        initial_score=50,
        initial_num_comments=5,
    )
    session.add(c)
    session.flush()
    tp = TrackedPost(
        candidate_post_id=c.id,
        user_id=user_id,
        polling_tier=tier,
        status=status,
        last_polled_at=last_polled_at,
    )
    session.add(tp)
    session.flush()
    return tp


# ---------------------------------------------------------------------------
# tier_for_age / interval_minutes_for_tier
# ---------------------------------------------------------------------------


def test_tier_for_age_boundaries():
    assert tier_for_age(0) == TIER_HOT
    assert tier_for_age(1) == TIER_HOT
    assert tier_for_age(24.0) == TIER_HOT             # 含 24h 上界
    assert tier_for_age(24.001) == TIER_COOLING       # 24h 之後跳 cooling
    assert tier_for_age(24 * 7) == TIER_COOLING       # 含 7d 上界
    assert tier_for_age(24 * 7 + 0.001) == TIER_ARCHIVE
    assert tier_for_age(24 * 30) == TIER_ARCHIVE      # 含 30d 上界
    assert tier_for_age(24 * 30 + 1) is None          # >30d → 升格 archived


def test_interval_minutes_for_tier():
    assert interval_minutes_for_tier(TIER_HOT) == 15
    assert interval_minutes_for_tier(TIER_COOLING) == 60
    assert interval_minutes_for_tier(TIER_ARCHIVE) == 360
    assert interval_minutes_for_tier("bogus") is None


# ---------------------------------------------------------------------------
# select_due_posts
# ---------------------------------------------------------------------------


def test_select_due_includes_never_polled(session):
    tp = _persist_tracked(session, last_polled_at=None)
    due = select_due_posts(session, now=NOW)
    assert [t.id for t in due] == [tp.id]


def test_select_due_excludes_recently_polled(session):
    _persist_tracked(session, last_polled_at=NOW - timedelta(minutes=5))    # tier=hot/15min
    due = select_due_posts(session, now=NOW)
    assert due == []


def test_select_due_includes_overdue(session):
    tp = _persist_tracked(session, last_polled_at=NOW - timedelta(minutes=16))
    due = select_due_posts(session, now=NOW)
    assert [t.id for t in due] == [tp.id]


def test_select_due_respects_tier_interval(session):
    """cooling tier 的貼文 30 分鐘前剛抓過，還沒過 1 小時 → 不 due。"""
    _persist_tracked(
        session,
        tier=TIER_COOLING,
        posted_hours_ago=48,
        last_polled_at=NOW - timedelta(minutes=30),
    )
    assert select_due_posts(session, now=NOW) == []


def test_select_due_excludes_archived_status(session):
    _persist_tracked(session, status=ARCHIVED_STATUS, last_polled_at=NOW - timedelta(days=1))
    assert select_due_posts(session, now=NOW) == []


# ---------------------------------------------------------------------------
# capture_snapshot
# ---------------------------------------------------------------------------


def test_capture_snapshot_writes_snapshot(session):
    tp = _persist_tracked(session, rid="abc1")
    scraper = FakeScraper(corpus=[_make_payload("abc1", score=250, num_comments=42, upvote=0.88)])
    result = capture_snapshot(session, scraper, tp, now=NOW)
    assert result.captured
    assert not result.archived
    snaps = session.scalars(select(PostSnapshot)).all()
    assert len(snaps) == 1
    assert snaps[0].score == 250
    assert snaps[0].num_comments == 42
    assert abs(snaps[0].upvote_ratio - 0.88) < 1e-6
    tp_after = session.get(TrackedPost, tp.id)
    assert tp_after.last_polled_at is not None
    assert tp_after.status == ACTIVE_STATUS


def test_capture_snapshot_demotes_tier_on_aging(session):
    """tier='hot' 但 post 已 26 小時 — 抓完應升 cooling。"""
    tp = _persist_tracked(session, rid="abc2", posted_hours_ago=26, tier=TIER_HOT)
    scraper = FakeScraper(corpus=[_make_payload("abc2")])
    result = capture_snapshot(session, scraper, tp, now=NOW)
    assert result.captured
    assert result.tier_changed == (TIER_HOT, TIER_COOLING)
    assert session.get(TrackedPost, tp.id).polling_tier == TIER_COOLING


def test_capture_snapshot_archives_after_30_days(session):
    """post >30 天 — 寫一筆 final snapshot 後 status='archived'。"""
    tp = _persist_tracked(session, rid="abc3", posted_hours_ago=24 * 31, tier=TIER_ARCHIVE)
    scraper = FakeScraper(corpus=[_make_payload("abc3")])
    result = capture_snapshot(session, scraper, tp, now=NOW)
    assert result.captured
    assert result.archived
    assert session.get(TrackedPost, tp.id).status == ARCHIVED_STATUS
    assert len(session.scalars(select(PostSnapshot)).all()) == 1


def test_capture_snapshot_post_missing_archives(session):
    """fetch_post 回 None → archived，不寫 snapshot。"""
    tp = _persist_tracked(session, rid="gone")
    scraper = FakeScraper(corpus=[])                              # corpus 不含 'gone'
    result = capture_snapshot(session, scraper, tp, now=NOW)
    assert not result.captured
    assert result.archived
    assert session.get(TrackedPost, tp.id).status == ARCHIVED_STATUS
    assert session.scalars(select(PostSnapshot)).all() == []


def test_capture_snapshot_scraper_error_keeps_active(session):
    """scraper raise → 不寫 snapshot、不 archived、有 last_polled_at（避免立刻重試）。"""

    class _BoomScraper(FakeScraper):
        def fetch_post(self, post_id):
            raise RuntimeError("boom")

    tp = _persist_tracked(session, rid="boom1")
    scraper = _BoomScraper(corpus=[_make_payload("boom1")])
    result = capture_snapshot(session, scraper, tp, now=NOW)
    assert not result.captured
    assert not result.archived
    assert result.error == "boom"
    tp_after = session.get(TrackedPost, tp.id)
    assert tp_after.status == ACTIVE_STATUS
    assert tp_after.last_polled_at == NOW


# ---------------------------------------------------------------------------
# run_polling — orchestration
# ---------------------------------------------------------------------------


def test_run_polling_captures_due_skips_recently_polled(session):
    due_tp = _persist_tracked(session, rid="r1", last_polled_at=None)
    _persist_tracked(session, rid="r2", last_polled_at=NOW - timedelta(minutes=2))
    scraper = FakeScraper(corpus=[
        _make_payload("r1", score=99),
        _make_payload("r2", score=88),
    ])
    stat = run_polling(session, scraper, now=NOW)
    assert stat.total_due == 1
    assert stat.captured == 1
    snaps = session.scalars(select(PostSnapshot)).all()
    assert len(snaps) == 1
    assert snaps[0].tracked_post_id == due_tp.id
    assert snaps[0].score == 99

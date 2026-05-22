"""services/enrichment.py — author profile lookup before scoring."""

from __future__ import annotations

from datetime import datetime, timezone

from reddit_tracker.models import CandidatePost
from reddit_tracker.scrapers.base import UserProfile
from reddit_tracker.scrapers.fake import FakeScraper
from reddit_tracker.services.enrichment import enrich_author_profiles


class _FixedProfileScraper(FakeScraper):
    """覆寫 fetch_user_about 回固定 profile，並計數呼叫次數。"""

    def __init__(self, profile_for: dict[str, UserProfile | None]):
        super().__init__(corpus=[])
        self.profile_for = profile_for
        self.calls: list[str] = []

    def fetch_user_about(self, username: str):
        self.calls.append(username)
        return self.profile_for.get(username)


_COUNTER = {"n": 0}


def _make_candidate(session, *, author: str | None, karma=None, created=None) -> CandidatePost:
    _COUNTER["n"] += 1
    c = CandidatePost(
        reddit_post_id=f"cid_{_COUNTER['n']:04d}",
        subreddit="test",
        title="t",
        author_username=author,
        author_karma=karma,
        author_created_utc=created,
    )
    session.add(c)
    session.flush()
    return c


def test_enrich_fills_karma_and_created(session):
    profile = UserProfile(
        username="alice",
        link_karma=500, comment_karma=300,
        created_utc=datetime(2020, 6, 1, tzinfo=timezone.utc),
    )
    scraper = _FixedProfileScraper({"alice": profile})
    c = _make_candidate(session, author="alice")
    stat = enrich_author_profiles(session, scraper, [c])
    assert stat.enriched == 1
    assert c.author_karma == 800
    assert c.author_created_utc.year == 2020


def test_enrich_skips_already_known(session):
    scraper = _FixedProfileScraper({})
    c = _make_candidate(session, author="known_user", karma=42)
    enrich_author_profiles(session, scraper, [c])
    assert scraper.calls == []        # 不該打 endpoint
    assert c.author_karma == 42


def test_enrich_dedups_same_author_within_batch(session):
    profile = UserProfile(
        username="bob", link_karma=100, comment_karma=50,
        created_utc=datetime(2021, 1, 1, tzinfo=timezone.utc),
    )
    scraper = _FixedProfileScraper({"bob": profile})
    c1 = _make_candidate(session, author="bob")
    c2 = _make_candidate(session, author="bob")
    c3 = _make_candidate(session, author="bob")
    stat = enrich_author_profiles(session, scraper, [c1, c2, c3])
    assert scraper.calls == ["bob"]                       # batch-local cache
    assert stat.looked_up == 1
    assert stat.enriched == 3
    for c in (c1, c2, c3):
        assert c.author_karma == 150


def test_enrich_handles_missing_profile(session):
    scraper = _FixedProfileScraper({"ghost": None})
    c = _make_candidate(session, author="ghost")
    stat = enrich_author_profiles(session, scraper, [c])
    assert stat.missing == 1
    assert c.author_karma is None
    assert c.author_created_utc is None

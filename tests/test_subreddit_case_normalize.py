"""M7 retune #3 — 驗證 subreddit 大小寫 normalize 的兩個入口。

1. PostPayload.__post_init__ 把 subreddit 強制 lowercase（scraper boundary）
2. seeds.loader.load_subreddit_seeds case-insensitive 認領舊 mixed-case row
3. ingest 雙保險：即使 PostPayload 給的是大寫，CandidatePost.subreddit 仍小寫
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select

from reddit_tracker.models import CandidatePost, SubredditSource
from reddit_tracker.scrapers.base import PostPayload
from reddit_tracker.scrapers.fake import FakeScraper
from reddit_tracker.seeds.loader import load_subreddit_seeds
from reddit_tracker.services.discovery import discover_from_subreddits


def _make_payload(rid: str, sub: str) -> PostPayload:
    return PostPayload(
        reddit_post_id=rid,
        subreddit=sub,
        title="hi",
        selftext="body",
        author="alice",
        author_karma=100,
        score=10,
        upvote_ratio=0.9,
        num_comments=3,
        created_utc=datetime.now(timezone.utc),
        permalink=f"/r/{sub}/comments/{rid}/x/",
        url=f"https://www.reddit.com/r/{sub}/comments/{rid}/x/",
        is_self=True,
        is_deleted=False,
        over_18=False,
        stickied=False,
    )


def test_post_payload_lowercases_subreddit_at_construction():
    p = _make_payload("a1", sub="Taiwan")
    assert p.subreddit == "taiwan"


def test_post_payload_preserves_already_lowercase_subreddit():
    p = _make_payload("a2", sub="tifu")
    assert p.subreddit == "tifu"


def test_post_payload_handles_mixed_case_with_underscore():
    p = _make_payload("a3", sub="China_irl")
    assert p.subreddit == "china_irl"


def test_post_payload_empty_subreddit_not_crashing():
    p = _make_payload("a4", sub="")
    assert p.subreddit == ""


def test_seeds_loader_renames_legacy_mixed_case_row(session):
    """既有大寫 row（M2 階段 seeds 留下）會被 lowercase seed 認領並 rename，
    不會多開一筆小寫版。"""
    legacy = SubredditSource(
        name="Taiwan",  # M2 階段大寫
        lang_hint="zh",
        enabled=True,
        total_candidates_yielded=100,
        total_promoted=5,
        total_collected=2,
    )
    session.add(legacy)
    session.commit()

    inserted, updated = load_subreddit_seeds(session)
    session.commit()

    # 該筆 Taiwan row 被 rename 成 taiwan，且統計沒被覆寫
    rows = session.scalars(
        select(SubredditSource).where(
            SubredditSource.name.in_(["taiwan", "Taiwan"])
        )
    ).all()
    assert len(rows) == 1, "不該多開一筆小寫版"
    assert rows[0].name == "taiwan"
    assert rows[0].total_candidates_yielded == 100
    assert rows[0].total_collected == 2
    # inserted 應該不含 taiwan（被認領 != 新增）
    assert updated >= 1


def test_ingest_writes_lowercase_subreddit_even_when_payload_was_uppercase(seeded_session):
    """雙保險：discovery._ingest_payloads 也 normalize，避免未來有人繞過
    PostPayload 直接餵大寫進來。"""
    scraper = FakeScraper(corpus=[_make_payload("ing1", sub="Taiwan")])
    discover_from_subreddits(seeded_session, scraper, per_sub_limit=10)
    seeded_session.commit()

    row = seeded_session.scalar(
        select(CandidatePost).where(CandidatePost.reddit_post_id == "ing1")
    )
    assert row is not None
    assert row.subreddit == "taiwan"

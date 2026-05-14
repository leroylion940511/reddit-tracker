"""SCHEDULE.md M2.12 — discovery 5 種情境。

case 1: subreddit /new 第一次掃，按 fetched 數寫入；source.last_polled_at 更新
case 2: 第二次掃同 sub，全部 dedupe（skipped_dupe == fetched）
case 3: disabled source 不被掃
case 4: skip_deleted=True 把 [deleted] payload 過濾掉
case 5: keyword discovery dedupe + 統計
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select

from reddit_tracker.models import CandidatePost, KeywordSeed, SubredditSource
from reddit_tracker.scrapers.base import PostPayload
from reddit_tracker.scrapers.fake import FakeScraper
from reddit_tracker.services.discovery import (
    discover_from_keywords,
    discover_from_subreddits,
)


def _make_payload(
    pid: str,
    *,
    sub: str = "Taiwan",
    title: str = "hi",
    author: str | None = "alice",
    deleted: bool = False,
    selftext: str = "body",
) -> PostPayload:
    return PostPayload(
        reddit_post_id=pid,
        subreddit=sub,
        title=title,
        selftext="[deleted]" if deleted else selftext,
        author=None if deleted else author,
        author_karma=100,
        score=10,
        upvote_ratio=0.9,
        num_comments=3,
        created_utc=datetime.now(timezone.utc),
        permalink=f"/r/{sub}/comments/{pid}/x/",
        url=f"https://www.reddit.com/r/{sub}/comments/{pid}/x/",
        is_self=True,
        is_deleted=deleted,
        over_18=False,
        stickied=False,
    )


# ---------------------------------------------------------------------------
# subreddit discovery
# ---------------------------------------------------------------------------


def test_subreddit_discovery_inserts_and_updates_stats(seeded_session):
    scraper = FakeScraper(
        corpus=[_make_payload("a1"), _make_payload("a2"), _make_payload("a3")]
    )
    stats = discover_from_subreddits(seeded_session, scraper, per_sub_limit=10)
    seeded_session.commit()

    taiwan_stat = next(s for s in stats if s.source == "subreddit:Taiwan")
    assert taiwan_stat.inserted == 3
    assert taiwan_stat.skipped_dupe == 0
    assert taiwan_stat.skipped_deleted == 0

    taiwan = seeded_session.scalar(
        select(SubredditSource).where(SubredditSource.name == "Taiwan")
    )
    assert taiwan.total_candidates_yielded == 3
    assert taiwan.last_polled_at is not None

    rows = seeded_session.scalars(
        select(CandidatePost).where(CandidatePost.subreddit == "Taiwan")
    ).all()
    assert {r.reddit_post_id for r in rows} == {"a1", "a2", "a3"}
    assert all(r.discovery_source == "subreddit:Taiwan" for r in rows)


def test_subreddit_discovery_dedupes_on_second_pass(seeded_session):
    scraper = FakeScraper(corpus=[_make_payload("dup1"), _make_payload("dup2")])
    discover_from_subreddits(seeded_session, scraper, per_sub_limit=10)
    seeded_session.commit()
    stats2 = discover_from_subreddits(seeded_session, scraper, per_sub_limit=10)
    seeded_session.commit()

    taiwan_stat = next(s for s in stats2 if s.source == "subreddit:Taiwan")
    assert taiwan_stat.fetched == 2
    assert taiwan_stat.inserted == 0
    assert taiwan_stat.skipped_dupe == 2

    taiwan = seeded_session.scalar(
        select(SubredditSource).where(SubredditSource.name == "Taiwan")
    )
    # 第二次沒 yield 任何新候選
    assert taiwan.total_candidates_yielded == 2


def test_disabled_source_is_skipped(seeded_session):
    taiwan = seeded_session.scalar(
        select(SubredditSource).where(SubredditSource.name == "Taiwan")
    )
    taiwan.enabled = False
    seeded_session.commit()

    scraper = FakeScraper(corpus=[_make_payload("x1")])
    stats = discover_from_subreddits(seeded_session, scraper, per_sub_limit=10)
    seeded_session.commit()

    assert not any(s.source == "subreddit:Taiwan" for s in stats)
    taiwan = seeded_session.scalar(
        select(SubredditSource).where(SubredditSource.name == "Taiwan")
    )
    assert taiwan.last_polled_at is None
    assert taiwan.total_candidates_yielded == 0


def test_deleted_payloads_are_skipped(seeded_session):
    scraper = FakeScraper(
        corpus=[
            _make_payload("ok1"),
            _make_payload("del1", deleted=True),
            _make_payload("ok2"),
        ]
    )
    stats = discover_from_subreddits(seeded_session, scraper, per_sub_limit=10)
    seeded_session.commit()

    taiwan_stat = next(s for s in stats if s.source == "subreddit:Taiwan")
    assert taiwan_stat.fetched == 3
    assert taiwan_stat.inserted == 2
    assert taiwan_stat.skipped_deleted == 1

    rows = seeded_session.scalars(
        select(CandidatePost.reddit_post_id).where(CandidatePost.subreddit == "Taiwan")
    ).all()
    assert set(rows) == {"ok1", "ok2"}


# ---------------------------------------------------------------------------
# keyword discovery
# ---------------------------------------------------------------------------


def test_keyword_discovery_dedupes_and_tracks_yield(seeded_session):
    # 給「更新」這個 seed 命中一個含「更新」的 fake 貼文
    fake = FakeScraper(
        corpus=[
            _make_payload("k1", title="這是更新文 #1"),
            _make_payload("k2", title="沒有相關詞 #2"),
        ]
    )
    stats = discover_from_keywords(seeded_session, fake, per_keyword_limit=10)
    seeded_session.commit()

    # 命中的關鍵字至少有 1 個 inserted；其他關鍵字 inserted=0
    inserted_total = sum(s.inserted for s in stats)
    assert inserted_total >= 1, "至少一個 keyword 該命中 'k1'"

    update_seed = seeded_session.scalar(
        select(KeywordSeed).where(KeywordSeed.keyword == "更新")
    )
    assert update_seed.last_polled_at is not None
    assert update_seed.total_candidates_yielded >= 1

    # 第二次跑：同樣的 corpus，全部 dedupe
    stats2 = discover_from_keywords(seeded_session, fake, per_keyword_limit=10)
    seeded_session.commit()
    assert sum(s.inserted for s in stats2) == 0
    assert sum(s.skipped_dupe for s in stats2) >= 1

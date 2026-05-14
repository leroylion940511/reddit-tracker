"""Discovery service — subreddit /new 主軸 + keyword 補充。

對應 SCHEDULE.md M2.9 + M2.10。流程：
    enabled sources → scraper.fetch_* → upsert candidate_posts(unique reddit_post_id)
                   → 累計 subreddit_sources / keyword_seeds 統計
                   → 寫回 last_polled_at
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import CandidatePost, KeywordSeed, SubredditSource
from ..scrapers.base import PostPayload, RedditScraper

logger = logging.getLogger(__name__)


@dataclass
class DiscoveryStat:
    source: str            # 'subreddit:Taiwan' / 'keyword:更新'
    fetched: int           # API 回傳筆數
    inserted: int          # 實際新寫入的 candidate
    skipped_deleted: int   # selftext='[deleted]' / author=None 被丟掉
    skipped_dupe: int      # reddit_post_id 已存在

    @property
    def yielded(self) -> int:
        """『此次掃到的有效新候選』— 寫進 source 表的 total_candidates_yielded。"""
        return self.inserted


# ---------------------------------------------------------------------------
# subreddit
# ---------------------------------------------------------------------------


def discover_from_subreddits(
    session: Session,
    scraper: RedditScraper,
    *,
    per_sub_limit: int = 50,
    skip_deleted: bool = True,
) -> list[DiscoveryStat]:
    sources = session.scalars(
        select(SubredditSource).where(SubredditSource.enabled == True)  # noqa: E712
    ).all()
    if not sources:
        logger.warning("沒有 enabled 的 subreddit_sources — 跑過 seeds.loader 了嗎？")
        return []

    stats: list[DiscoveryStat] = []
    for source in sources:
        try:
            payloads = scraper.fetch_new(source.name, limit=per_sub_limit)
        except Exception as e:  # noqa: BLE001 — 任一 sub 壞掉不阻塞其他
            logger.error("fetch_new(%s) 失敗: %s", source.name, e)
            continue

        stat = _ingest_payloads(
            session,
            payloads,
            discovery_source=f"subreddit:{source.name}",
            skip_deleted=skip_deleted,
            lang_hint=source.lang_hint,
        )
        source.last_polled_at = datetime.now(timezone.utc)
        source.total_candidates_yielded += stat.yielded
        stats.append(stat)

    session.flush()
    return stats


# ---------------------------------------------------------------------------
# keyword
# ---------------------------------------------------------------------------


def discover_from_keywords(
    session: Session,
    scraper: RedditScraper,
    *,
    per_keyword_limit: int = 50,
    time_filter: str = "day",
    skip_deleted: bool = True,
) -> list[DiscoveryStat]:
    seeds = session.scalars(
        select(KeywordSeed).where(KeywordSeed.enabled == True)  # noqa: E712
    ).all()
    if not seeds:
        logger.warning("沒有 enabled 的 keyword_seeds — 跑過 seeds.loader 了嗎？")
        return []

    stats: list[DiscoveryStat] = []
    for seed in seeds:
        try:
            payloads = scraper.search(
                seed.keyword,
                subreddit="all",
                time_filter=time_filter,
                limit=per_keyword_limit,
            )
        except Exception as e:  # noqa: BLE001
            logger.error("search(%s) 失敗: %s", seed.keyword, e)
            continue

        stat = _ingest_payloads(
            session,
            payloads,
            discovery_source=f"keyword:{seed.keyword}",
            skip_deleted=skip_deleted,
            lang_hint=seed.lang,
        )
        seed.last_polled_at = datetime.now(timezone.utc)
        seed.total_candidates_yielded += stat.yielded
        stats.append(stat)

    session.flush()
    return stats


# ---------------------------------------------------------------------------
# internals
# ---------------------------------------------------------------------------


def _ingest_payloads(
    session: Session,
    payloads: list[PostPayload],
    *,
    discovery_source: str,
    skip_deleted: bool,
    lang_hint: str | None,
) -> DiscoveryStat:
    stat = DiscoveryStat(
        source=discovery_source,
        fetched=len(payloads),
        inserted=0,
        skipped_deleted=0,
        skipped_dupe=0,
    )

    if not payloads:
        return stat

    existing_ids = set(
        session.scalars(
            select(CandidatePost.reddit_post_id).where(
                CandidatePost.reddit_post_id.in_([p.reddit_post_id for p in payloads])
            )
        ).all()
    )

    for p in payloads:
        if p.reddit_post_id in existing_ids:
            stat.skipped_dupe += 1
            continue
        if skip_deleted and p.is_deleted:
            stat.skipped_deleted += 1
            continue
        session.add(
            CandidatePost(
                reddit_post_id=p.reddit_post_id,
                subreddit=p.subreddit,
                title=p.title,
                selftext=p.selftext,
                permalink=p.permalink,
                author_username=p.author,
                author_karma=p.author_karma,
                posted_at=p.created_utc,
                discovery_source=discovery_source,
                initial_score=p.score,
                initial_num_comments=p.num_comments,
                upvote_ratio=p.upvote_ratio,
                lang=lang_hint,
                meta_json={
                    "url": p.url,
                    "is_self": p.is_self,
                    "over_18": p.over_18,
                    "stickied": p.stickied,
                    **p.extras,
                },
            )
        )
        existing_ids.add(p.reddit_post_id)  # 同一批內也防重
        stat.inserted += 1
    return stat

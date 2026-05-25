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


def _lang_compatible(seed_lang: str | None, sub_lang_hint: str | None) -> bool:
    """zh seed → zh / mixed / None sub；en seed → en / mixed / None sub。

    無 lang 資訊（None / 'mixed'）兩邊都通行，避免過度限縮。
    """
    if not seed_lang or seed_lang == "mixed":
        return True
    if not sub_lang_hint or sub_lang_hint == "mixed":
        return True
    return seed_lang == sub_lang_hint


def discover_from_keywords(
    session: Session,
    scraper: RedditScraper,
    *,
    per_keyword_limit: int = 30,
    time_filter: str = "day",
    skip_deleted: bool = True,
) -> list[DiscoveryStat]:
    """Keyword discovery — 對每個 seed 在 lang-compatible enabled subs 內
    `restrict_sr=on` 搜尋（fan-out）。

    為何不打 all-reddit search？
        Public JSON 的 `/search.json` 對 unauthenticated 一律 403（M1 probe
        實測）。OAuth path 才能搜全站。fan-out 到「我們已知關心的 subs」
        雖然失去 `r/legaladvice` 之類未追蹤 sub 的覆蓋，但保留 keyword 撈
        「同 sub /new 已被淘汰的舊文」的價值，且每個 (seed, sub) 失敗不影響
        其他組合。

    回傳：每個 keyword 一筆 aggregated DiscoveryStat（fetched / inserted /
    dupe / deleted 跨所有 sub 加總）。
    """
    seeds = session.scalars(
        select(KeywordSeed).where(KeywordSeed.enabled == True)  # noqa: E712
    ).all()
    subs = session.scalars(
        select(SubredditSource).where(SubredditSource.enabled == True)  # noqa: E712
    ).all()

    if not seeds:
        logger.warning("沒有 enabled 的 keyword_seeds — 跑過 seeds.loader 了嗎？")
        return []
    if not subs:
        logger.warning("沒有 enabled 的 subreddit_sources，keyword discovery 無 sub 可打")
        return []

    stats: list[DiscoveryStat] = []
    for seed in seeds:
        agg = DiscoveryStat(
            source=f"keyword:{seed.keyword}",
            fetched=0,
            inserted=0,
            skipped_deleted=0,
            skipped_dupe=0,
        )
        searched_subs = 0
        for sub in subs:
            if not _lang_compatible(seed.lang, sub.lang_hint):
                continue
            try:
                payloads = scraper.search(
                    seed.keyword,
                    subreddit=sub.name,
                    time_filter=time_filter,
                    limit=per_keyword_limit,
                )
            except Exception as e:  # noqa: BLE001 — 該 sub 壞掉不阻塞其他
                logger.warning(
                    "search(seed=%s, sub=%s) 失敗: %s",
                    seed.keyword, sub.name, e,
                )
                continue
            searched_subs += 1
            sub_stat = _ingest_payloads(
                session,
                payloads,
                discovery_source=f"keyword:{seed.keyword}",
                skip_deleted=skip_deleted,
                lang_hint=sub.lang_hint or seed.lang,
            )
            agg.fetched += sub_stat.fetched
            agg.inserted += sub_stat.inserted
            agg.skipped_deleted += sub_stat.skipped_deleted
            agg.skipped_dupe += sub_stat.skipped_dupe

        seed.last_polled_at = datetime.now(timezone.utc)
        seed.total_candidates_yielded += agg.yielded
        logger.info(
            "keyword '%s' fan-out: searched_subs=%d fetched=%d inserted=%d "
            "dupe=%d deleted=%d",
            seed.keyword, searched_subs, agg.fetched, agg.inserted,
            agg.skipped_dupe, agg.skipped_deleted,
        )
        stats.append(agg)

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
    # 立刻 flush — 讓下一次 `_ingest_payloads` 的 SELECT 看得到本次新加的
    # pending rows。沒這行的話，keyword fan-out 同篇貼文被兩個 (seed,sub) 命中時，
    # 第二次 SELECT 看不到第一次的 pending insert → batch flush 撞 UNIQUE constraint
    # → 整支 scheduler 死。
    if stat.inserted:
        session.flush()
    return stat

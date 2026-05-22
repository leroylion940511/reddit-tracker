"""Candidate enrichment — 在進 scoring 前補資料。

公開 JSON 的 `/r/<sub>/new.json` 不直接帶 author_karma / author_created_utc，
但 `/user/<name>/about.json` 可以拿到（probe 顯示 83% 成功率）。

設計取捨：
- 不在 discovery 階段補，因為 discovery 每輪 candidate 量大（~800）會把 throttle
  時間拉到超過 60min interval；scoring 階段每輪只取 batch_limit=50，throttle
  影響可控
- 同一作者一輪內只查一次（scraper 端已有 24h cache，這裡再做 batch-local dedup）
- 失敗（None）寫入 DB 後，下次 batch 不再重試（scoring rules 已對 None 放行）

對應 PROGRESS.md 「public JSON 拿不到 karma」這條已知坑的解法。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy.orm import Session

from ..models import CandidatePost
from ..scrapers.base import RedditScraper

logger = logging.getLogger(__name__)


@dataclass
class EnrichmentStat:
    total: int
    looked_up: int       # 實際打 about endpoint 的次數（< total 因為同作者去重）
    enriched: int        # 成功補到 karma 或 created_utc 的 candidate 數
    missing: int         # about endpoint 回 None（shadowban / deleted）


def enrich_author_profiles(
    session: Session,
    scraper: RedditScraper,
    candidates: list[CandidatePost],
) -> EnrichmentStat:
    """對 batch 內 author_karma IS NULL 的 candidate 補 karma / account_age。

    Mutate candidate row in-place（由呼叫端 commit / flush）。
    """
    stat = EnrichmentStat(total=len(candidates), looked_up=0, enriched=0, missing=0)
    pending = [c for c in candidates if c.author_karma is None and c.author_username]
    if not pending:
        return stat

    # batch-local cache：同一作者在這輪內只打一次
    profile_cache: dict[str, object] = {}     # username -> UserProfile | None
    for c in pending:
        name = c.author_username
        if name not in profile_cache:
            profile = scraper.fetch_user_about(name)
            profile_cache[name] = profile
            stat.looked_up += 1
        else:
            profile = profile_cache[name]

        if profile is None:
            stat.missing += 1
            continue

        # 寫回 candidate；total_karma 用 link_karma + comment_karma 合計
        total_karma = profile.total_karma  # type: ignore[union-attr]
        if total_karma is not None:
            c.author_karma = total_karma
            stat.enriched += 1
        if profile.created_utc is not None:  # type: ignore[union-attr]
            c.author_created_utc = profile.created_utc  # type: ignore[union-attr]

    session.flush()
    logger.info(
        "enrich_author_profiles: total=%d looked_up=%d enriched=%d missing=%d",
        stat.total, stat.looked_up, stat.enriched, stat.missing,
    )
    return stat

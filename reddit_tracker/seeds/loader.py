"""Seeds loader — 冪等寫入 subreddit_sources / keyword_seeds 表。

對應 SCHEDULE.md M2.8。設計：
- 不刪除既有 row（不覆寫 enabled / 統計欄位）
- 只 INSERT 沒見過的新 seed
- 既有 row 若 lang_hint / category 為空才補；其他欄位完全不動（避免覆蓋 M7 調校）
"""

from __future__ import annotations

import logging

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import KeywordSeed, SubredditSource
from .keyword_seeds import KEYWORD_SEEDS
from .subreddit_list import SUBREDDIT_SEEDS

logger = logging.getLogger(__name__)


def load_subreddit_seeds(session: Session) -> tuple[int, int]:
    """回傳 (inserted, updated) 計數。

    比對 existing row 走 case-insensitive — 既有 mixed-case row（M2 階段
    seeds 大小寫不一致留下的）會被 lowercase canonical seed 認領並 rename，
    不會在 DB 再開一筆小寫版。
    """
    inserted = updated = 0
    for seed in SUBREDDIT_SEEDS:
        existing = session.scalar(
            select(SubredditSource).where(func.lower(SubredditSource.name) == seed.name)
        )
        if existing is None:
            session.add(
                SubredditSource(name=seed.name, lang_hint=seed.language, enabled=True)
            )
            inserted += 1
            continue
        # 既存 row：name 若仍是大寫變體，rename 成 canonical lowercase
        if existing.name != seed.name:
            existing.name = seed.name
            updated += 1
        # 只補空欄位，不覆寫 enabled / 統計
        if not existing.lang_hint:
            existing.lang_hint = seed.language
            updated += 1
    session.flush()
    logger.info("subreddit seeds: +%d new, %d back-filled", inserted, updated)
    return inserted, updated


def load_keyword_seeds(session: Session) -> tuple[int, int]:
    inserted = updated = 0
    for seed in KEYWORD_SEEDS:
        existing = session.scalar(
            select(KeywordSeed).where(KeywordSeed.keyword == seed.term)
        )
        if existing is None:
            session.add(
                KeywordSeed(
                    keyword=seed.term,
                    lang=seed.language,
                    category=seed.intent,
                    enabled=True,
                )
            )
            inserted += 1
            continue
        if not existing.lang:
            existing.lang = seed.language
            updated += 1
        if not existing.category:
            existing.category = seed.intent
            updated += 1
    session.flush()
    logger.info("keyword seeds: +%d new, %d back-filled", inserted, updated)
    return inserted, updated


def load_all(session: Session) -> dict[str, tuple[int, int]]:
    return {
        "subreddit_sources": load_subreddit_seeds(session),
        "keyword_seeds": load_keyword_seeds(session),
    }

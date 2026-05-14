"""Scraper factory — 依環境變數切 public-json / praw / fake。

對應 SCHEDULE.md M2.7。沿用 v3 的 factory pattern（PROGRESS.md 第 101 行）。

環境變數：
    REDDIT_SCRAPER=public_json  (預設，M1 階段，無需 OAuth)
    REDDIT_SCRAPER=praw         (OAuth 過了再切，需要 CLIENT_ID/SECRET)
    REDDIT_SCRAPER=fake         (測試用，M2.6 補)
"""

from __future__ import annotations

import logging
import os

from .base import RedditScraper
from .json_public import PublicJSONScraper

logger = logging.getLogger(__name__)


def build_scraper(kind: str | None = None) -> RedditScraper:
    kind = (kind or os.getenv("REDDIT_SCRAPER", "public_json")).lower()
    user_agent = os.getenv("REDDIT_USER_AGENT", "reddit_tracker/0.1 by unknown")

    if kind == "public_json":
        logger.info(
            "Using PublicJSONScraper (no OAuth). "
            "M5 收藏追蹤的 duplicates / user_submissions 在這條路徑下不穩定，"
            "正式運轉前請切到 REDDIT_SCRAPER=praw"
        )
        return PublicJSONScraper(user_agent=user_agent)

    if kind == "praw":
        from .praw_oauth import PRAWScraper  # 延後 import — 避免 OAuth 還沒過時誤觸

        client_id = os.getenv("REDDIT_CLIENT_ID")
        client_secret = os.getenv("REDDIT_CLIENT_SECRET")
        if not (client_id and client_secret):
            raise RuntimeError(
                "REDDIT_SCRAPER=praw 但 REDDIT_CLIENT_ID/REDDIT_CLIENT_SECRET 未設。"
                "申請通過後填進 .env 再啟用。"
            )
        return PRAWScraper(
            client_id=client_id,
            client_secret=client_secret,
            user_agent=user_agent,
        )

    if kind == "fake":
        from .fake import FakeScraper

        return FakeScraper()

    raise ValueError(f"unknown REDDIT_SCRAPER={kind!r}")

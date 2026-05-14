"""Reddit scraper abstraction.

設計核心：抽象介面 `RedditScraper` + 統一 payload `PostPayload`，讓上層
（discovery / scoring / detection）不需要關心資料來源是 PRAW OAuth 還是 public
JSON endpoint。OAuth 申請通過後切換實作即可。

對應 SCHEDULE.md M2.5。M1 階段先有介面 + PublicJSONScraper 實作，先把
discovery 流水線跑通。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Iterable


@dataclass(frozen=True)
class PostPayload:
    """Reddit 貼文的統一表示。對應企劃書 §五 candidate_posts schema 核心欄位。

    所有 scraper 實作必須吐這個 dataclass — 上層消費端不感知資料來源差異。
    PRAW 來源會多帶些欄位（例如 `praw_submission` raw object）放 extras 裡。
    """

    reddit_post_id: str           # base36 ID，例如 "1abc2de"
    subreddit: str                # 不含 r/ 前綴
    title: str
    selftext: str                 # 自貼文內文；link post 為空字串
    author: str | None            # None 表示 deleted / removed
    author_karma: int | None      # public JSON 來源拿不到，None 表未知
    score: int                    # net upvotes
    upvote_ratio: float | None    # 0.0–1.0；public JSON 來源可能拿不到
    num_comments: int
    created_utc: datetime         # UTC tz-aware
    permalink: str                # "/r/Taiwan/comments/abc/..." 不含 host
    url: str                      # 對 link post 是外連；對 self post 等同 reddit URL
    is_self: bool
    is_deleted: bool              # selftext in ("[deleted]", "[removed]")
    over_18: bool
    stickied: bool

    extras: dict = field(default_factory=dict)   # provider-specific raw fields

    @property
    def full_url(self) -> str:
        return f"https://www.reddit.com{self.permalink}"


class RedditScraper(ABC):
    """抽象 scraper。實作見 json_public.py / praw_oauth.py。

    所有方法都應該是同步的；上層需要並發就用 `concurrent.futures` 包。
    早期不引 asyncio 避免 PRAW（同步庫）混進來時的整合成本。
    """

    @abstractmethod
    def fetch_new(self, subreddit: str, limit: int = 50) -> list[PostPayload]:
        """抓 `/r/<sub>/new`，依時間倒序返回最多 `limit` 篇。"""

    @abstractmethod
    def search(
        self,
        query: str,
        subreddit: str = "all",
        time_filter: str = "day",
        limit: int = 50,
    ) -> list[PostPayload]:
        """跨 sub 關鍵字搜尋。"""

    @abstractmethod
    def fetch_post(self, post_id: str) -> PostPayload | None:
        """取單篇貼文。404 / removed 回 None（呼叫端決定如何處理）。"""

    # 以下兩個是 M5 才用到的、需要 OAuth 才有完整支援的方法。
    # public JSON 實作會 raise NotImplementedError，由 factory 在啟動時
    # 警告使用者「目前 scraper 不支援收藏追蹤層」。

    @abstractmethod
    def fetch_duplicates(self, post_id: str) -> list[PostPayload]:
        """submission.duplicates() — 拿所有 crosspost。M5 收藏追蹤用。"""

    @abstractmethod
    def fetch_user_submissions(self, username: str, limit: int = 20) -> list[PostPayload]:
        """作者近期貼文。M5 author_followup 偵測用。"""


def _parse_created_utc(ts: float) -> datetime:
    """Reddit 給 epoch seconds (float)；統一轉 UTC tz-aware datetime。"""
    return datetime.fromtimestamp(ts, tz=timezone.utc)


def _detect_deleted(selftext: str | None, author: str | None) -> bool:
    return (
        selftext in ("[deleted]", "[removed]")
        or author in (None, "[deleted]")
    )


# 暫無泛用工具；保留 helper 留給 public JSON / PRAW 兩端共用 normalization 邏輯。
__all__ = [
    "PostPayload",
    "RedditScraper",
    "_parse_created_utc",
    "_detect_deleted",
]

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
class UserProfile:
    """作者 about info — 給 M3 硬規則的 karma / account_age 用。

    PublicJSONScraper 透過 `/user/<name>/about.json` 取得；OAuth 路徑也走同樣 endpoint
    （PRAW redditor.link_karma + comment_karma + created_utc 對應同一份資料）。
    """

    username: str
    link_karma: int | None
    comment_karma: int | None
    created_utc: datetime | None       # 帳號註冊時間，UTC tz-aware

    @property
    def total_karma(self) -> int | None:
        if self.link_karma is None and self.comment_karma is None:
            return None
        return (self.link_karma or 0) + (self.comment_karma or 0)


@dataclass(frozen=True)
class CommentNode:
    """攤平後的單一留言節點，巢狀以 depth 表示而非 children 物件參考。

    Reddit 留言原生是樹狀，但 M5 hot_reply 偵測 / M6 prompt 組裝都用「依時間或分數
    排序的扁平 list + depth 標籤」處理起來更乾淨。樹結構由 `services/comment_tree.py`
    在抓下來後做一次 flatten。

    `is_more_placeholder`: Reddit comment tree 用 `kind=more` 表示「還有省略的留言」。
    public JSON 拿不到 OAuth-only 的 /api/morechildren，這類節點只記下 placeholder
    供上層決定是否在 prompt 註明 "more comments omitted"。
    """

    comment_id: str                   # base36，例如 "k4ab2c3"
    parent_id: str                    # 父節點 id；最上層的 parent_id 等同 submission t3_xxx
    author: str | None                # None = deleted/removed
    body: str                         # 留言內文
    score: int
    created_utc: datetime
    depth: int                        # 0 = top-level，依層遞增
    is_submitter: bool                # comment.author == submission.author
    is_more_placeholder: bool = False
    omitted_count: int = 0            # 當 is_more_placeholder 時，Reddit 估計省略的留言數


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

    # 以下三個給 M3 硬規則 / M5 追蹤層 / M6 問答用。
    # 走 public JSON path（無 OAuth）也都實測可行，見 docs/m1_public_endpoints_probe.md。

    @abstractmethod
    def fetch_duplicates(self, post_id: str) -> list[PostPayload]:
        """submission.duplicates() — 拿所有 crosspost。M5 收藏追蹤用。

        Public JSON path 下大多 200；偶發 403（疑似 NSFW / quarantine）回 []。
        """

    @abstractmethod
    def fetch_user_submissions(self, username: str, limit: int = 20) -> list[PostPayload]:
        """作者近期貼文。M5 author_followup 偵測用。"""

    @abstractmethod
    def fetch_user_about(self, username: str) -> UserProfile | None:
        """作者 about info — `/user/<name>/about.json`。

        給 M3 硬規則補 author_karma / account_age。Shadowbanned 或 deleted 用戶會
        回 404 / 403 → None。實作端應做 cache（同 username 短時間多次查只打一次）。
        """

    @abstractmethod
    def fetch_comment_tree(
        self, post_id: str, *, limit: int = 500, depth: int = 10
    ) -> list[CommentNode]:
        """`/comments/<id>.json` — 取留言樹並攤平。

        - 樹遞迴展開後吐扁平 list；巢狀以 `CommentNode.depth` 標示
        - Reddit 的 `kind=more` 節點轉成 `is_more_placeholder=True` 的 CommentNode
          （public path 無法展開，OAuth-only）
        - M5 用 score 排序拿 hot_reply、過濾 is_submitter 拿 author_reply
        - M6 問答 context 組裝直接吃這個 list
        """


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
    "CommentNode",
    "PostPayload",
    "RedditScraper",
    "UserProfile",
    "_parse_created_utc",
    "_detect_deleted",
]

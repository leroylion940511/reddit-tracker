"""FakeScraper — 給測試與 OAuth 等待期間的離線開發用。

對應 SCHEDULE.md M2.6。沿用 v3 fake-scraper pattern。設計重點：
- 啟動時生 50 筆假 PostPayload（半中半英、半 storytelling 半 NSFW gate）
- 介面與 RedditScraper 完全一致；可注入到 discovery / scoring 測試
- 支援「指定 corpus」建構，給 unit test 用客製化資料集
"""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timedelta, timezone

from .base import PostPayload, RedditScraper

logger = logging.getLogger(__name__)


def _fake_id(seed: str, idx: int) -> str:
    """生成 base36-ish 看起來像真的 reddit ID。"""
    h = hashlib.sha1(f"{seed}:{idx}".encode()).hexdigest()
    return h[:7]  # 真 ID 長度大約 7 字元


def _make_default_corpus(now: datetime) -> list[PostPayload]:
    """50 筆種子假資料，跨 5 個 sub、混合中英、覆蓋邊界狀況。"""
    subs = ["Taiwan", "tifu", "AmItheAsshole", "HongKong", "relationship_advice"]
    authors = ["alice", "bob", "carol", "dave", "evan"]
    titles_zh = [
        "上班遲到被老闆抓到，後來發生這種事",
        "結婚紀念日老公做了一件讓我傻眼的事",
        "我家貓會講話",
        "颱風天買到的便當",
        "在台北捷運遇到怪人",
    ]
    titles_en = [
        "TIFU by texting my boss at 3am",
        "AITA for ghosting my best friend",
        "Update: I finally confronted my landlord",
        "My neighbor's cat won't stop staring",
        "Found a $50 bill in an old jacket",
    ]
    corpus: list[PostPayload] = []
    for i in range(50):
        sub = subs[i % 5]
        author = authors[i % 5] if i % 7 else None  # 每 7 篇一個 deleted author
        is_zh = sub in ("Taiwan", "HongKong")
        title = (titles_zh if is_zh else titles_en)[i % 5]
        title = f"{title} #{i:02d}"
        # 時間從 24h 內回推，越新的 idx 越大
        posted = now - timedelta(minutes=30 * (50 - i))
        selftext = "" if i % 5 == 0 else f"假內容 #{i}，這只是給 FakeScraper 測試用。"
        if i % 13 == 0:
            selftext = "[deleted]"   # 模擬被刪
        corpus.append(
            PostPayload(
                reddit_post_id=_fake_id("default", i),
                subreddit=sub,
                title=title,
                selftext=selftext,
                author=author,
                author_karma=1000 + i * 17,
                score=10 + (i * 13) % 500,
                upvote_ratio=0.5 + (i % 50) / 100,
                num_comments=(i * 3) % 80,
                created_utc=posted.astimezone(timezone.utc),
                permalink=f"/r/{sub}/comments/{_fake_id('default', i)}/fake/",
                url=f"https://www.reddit.com/r/{sub}/comments/{_fake_id('default', i)}/fake/",
                is_self=True,
                is_deleted=selftext == "[deleted]" or author is None,
                over_18=(sub == "tifu" and i % 4 == 0),
                stickied=(i == 0),
                extras={"_fake": True, "_index": i},
            )
        )
    return corpus


class FakeScraper(RedditScraper):
    """In-memory fixture scraper。沒有網路呼叫。"""

    def __init__(self, corpus: list[PostPayload] | None = None) -> None:
        now = datetime.now(timezone.utc)
        self._corpus: list[PostPayload] = (
            list(corpus) if corpus is not None else _make_default_corpus(now)
        )
        self._by_id: dict[str, PostPayload] = {p.reddit_post_id: p for p in self._corpus}
        logger.info("FakeScraper loaded with %d posts", len(self._corpus))

    # 測試輔助：注入額外資料 / 清空
    def add(self, post: PostPayload) -> None:
        self._corpus.append(post)
        self._by_id[post.reddit_post_id] = post

    def clear(self) -> None:
        self._corpus.clear()
        self._by_id.clear()

    # ------------------------------------------------------------------
    # RedditScraper interface
    # ------------------------------------------------------------------

    def fetch_new(self, subreddit: str, limit: int = 50) -> list[PostPayload]:
        target = subreddit.lower()
        matched = [p for p in self._corpus if p.subreddit.lower() == target]
        matched.sort(key=lambda p: p.created_utc, reverse=True)
        return matched[:limit]

    def search(
        self,
        query: str,
        subreddit: str = "all",
        time_filter: str = "day",
        limit: int = 50,
    ) -> list[PostPayload]:
        q = query.lower()
        scope = (
            self._corpus
            if subreddit == "all"
            else [p for p in self._corpus if p.subreddit.lower() == subreddit.lower()]
        )
        hits = [
            p for p in scope
            if q in (p.title or "").lower() or q in (p.selftext or "").lower()
        ]
        hits.sort(key=lambda p: p.created_utc, reverse=True)
        return hits[:limit]

    def fetch_post(self, post_id: str) -> PostPayload | None:
        return self._by_id.get(post_id)

    def fetch_duplicates(self, post_id: str) -> list[PostPayload]:
        # Fake：同 author 同 sub 的其他貼文當作 crosspost 模擬
        anchor = self._by_id.get(post_id)
        if not anchor:
            return []
        return [
            p for p in self._corpus
            if p.reddit_post_id != post_id
            and p.subreddit == anchor.subreddit
            and p.author == anchor.author
        ]

    def fetch_user_submissions(self, username: str, limit: int = 20) -> list[PostPayload]:
        matched = [p for p in self._corpus if p.author == username]
        matched.sort(key=lambda p: p.created_utc, reverse=True)
        return matched[:limit]

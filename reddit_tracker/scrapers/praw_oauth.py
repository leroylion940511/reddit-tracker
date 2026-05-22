"""PRAW-based scraper — 等 OAuth 申請通過後啟用。

設計與 PublicJSONScraper 介面對等，差別只在資料來源與額外能力：
- 100 QPM（vs public ~10 QPM）
- duplicates / user submissions 穩定可用
- 可拿 author_karma（透過 redditor.link_karma + comment_karma）

M1 階段 OAuth 還沒過，這個 class 的 fetch_* 方法**不要**真的呼叫 PRAW，
保留為 skeleton 以利 factory 編譯通過；OAuth 過了之後再填實作（M2 任務）。
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

import praw  # type: ignore[import-untyped]

from .base import (
    CommentNode,
    PostPayload,
    RedditScraper,
    UserProfile,
    _detect_deleted,
    _parse_created_utc,
)

logger = logging.getLogger(__name__)


class PRAWScraper(RedditScraper):
    """PRAW wrapper。M2 任務 2.5 補實作；現在先放骨架。"""

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        user_agent: str,
    ) -> None:
        if not (client_id and client_secret and user_agent):
            raise ValueError("PRAWScraper 需要 client_id / client_secret / user_agent")
        self._reddit = praw.Reddit(
            client_id=client_id,
            client_secret=client_secret,
            user_agent=user_agent,
        )
        # read-only mode 確認；未設 username/password 時 PRAW 預設 read-only
        logger.info("PRAW initialized (read_only=%s)", self._reddit.read_only)

    # ------------------------------------------------------------------
    # RedditScraper interface — M2 補完整實作
    # ------------------------------------------------------------------

    def fetch_new(self, subreddit: str, limit: int = 50) -> list[PostPayload]:
        out: list[PostPayload] = []
        for sub in self._reddit.subreddit(subreddit).new(limit=limit):
            out.append(_submission_to_payload(sub))
        return out

    def search(
        self,
        query: str,
        subreddit: str = "all",
        time_filter: str = "day",
        limit: int = 50,
    ) -> list[PostPayload]:
        out: list[PostPayload] = []
        for sub in self._reddit.subreddit(subreddit).search(
            query, time_filter=time_filter, limit=limit, sort="new"
        ):
            out.append(_submission_to_payload(sub))
        return out

    def fetch_post(self, post_id: str) -> PostPayload | None:
        try:
            sub = self._reddit.submission(id=post_id)
            # 觸發 lazy load
            _ = sub.title
        except Exception as e:  # noqa: BLE001 — PRAW 異常多樣，統一吞
            logger.warning("fetch_post(%s) 失敗: %s", post_id, e)
            return None
        return _submission_to_payload(sub)

    def fetch_duplicates(self, post_id: str) -> list[PostPayload]:
        sub = self._reddit.submission(id=post_id)
        return [_submission_to_payload(d) for d in sub.duplicates()]

    def fetch_user_submissions(self, username: str, limit: int = 20) -> list[PostPayload]:
        try:
            redditor = self._reddit.redditor(username)
            return [_submission_to_payload(s) for s in redditor.submissions.new(limit=limit)]
        except Exception as e:  # noqa: BLE001
            logger.warning("fetch_user_submissions(%s) 失敗: %s", username, e)
            return []

    def fetch_user_about(self, username: str) -> UserProfile | None:
        try:
            r = self._reddit.redditor(username)
            return UserProfile(
                username=username,
                link_karma=int(r.link_karma) if r.link_karma is not None else None,
                comment_karma=int(r.comment_karma) if r.comment_karma is not None else None,
                created_utc=datetime.fromtimestamp(r.created_utc, tz=timezone.utc),
            )
        except Exception as e:  # noqa: BLE001
            logger.warning("fetch_user_about(%s) 失敗: %s", username, e)
            return None

    def fetch_comment_tree(
        self, post_id: str, *, limit: int = 500, depth: int = 10
    ) -> list[CommentNode]:
        try:
            sub = self._reddit.submission(id=post_id)
            sub.comment_limit = limit
            sub.comments.replace_more(limit=0)
            submitter = sub.author.name if sub.author else None
            out: list[CommentNode] = []
            _walk_praw_forest(sub.comments, submitter=submitter, depth=0,
                              parent_id=f"t3_{post_id}", out=out, max_depth=depth)
            return out
        except Exception as e:  # noqa: BLE001
            logger.warning("fetch_comment_tree(%s) 失敗: %s", post_id, e)
            return []


def _walk_praw_forest(forest, *, submitter, depth, parent_id, out, max_depth):
    if depth > max_depth:
        return
    for c in forest:
        author = c.author.name if c.author else None
        out.append(
            CommentNode(
                comment_id=c.id,
                parent_id=parent_id,
                author=author,
                body=c.body or "",
                score=int(c.score),
                created_utc=_parse_created_utc(c.created_utc),
                depth=depth,
                is_submitter=bool(submitter and author == submitter),
            )
        )
        if hasattr(c, "replies"):
            _walk_praw_forest(c.replies, submitter=submitter, depth=depth + 1,
                              parent_id=f"t1_{c.id}", out=out, max_depth=max_depth)


def _submission_to_payload(sub) -> PostPayload:
    author_name = sub.author.name if sub.author else None
    selftext = sub.selftext or ""
    return PostPayload(
        reddit_post_id=sub.id,
        subreddit=str(sub.subreddit),
        title=sub.title,
        selftext=selftext,
        author=author_name,
        author_karma=None,  # 拿 karma 要再打 redditor.link_karma — 不在熱路徑做
        score=int(sub.score),
        upvote_ratio=float(sub.upvote_ratio) if sub.upvote_ratio is not None else None,
        num_comments=int(sub.num_comments),
        created_utc=datetime.fromtimestamp(sub.created_utc, tz=timezone.utc),
        permalink=sub.permalink,
        url=sub.url,
        is_self=bool(sub.is_self),
        is_deleted=_detect_deleted(selftext, author_name),
        over_18=bool(sub.over_18),
        stickied=bool(sub.stickied),
        extras={
            "domain": getattr(sub, "domain", None),
            "link_flair_text": getattr(sub, "link_flair_text", None),
            "num_crossposts": getattr(sub, "num_crossposts", None),
        },
    )

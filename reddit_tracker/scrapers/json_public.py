"""Public JSON endpoint scraper — 不需要 OAuth。

Reddit 的 `<url>.json` 後綴對未認證請求仍可用，速率限制大約 10 req/min（per IP），
TOS 允許 personal use。本實作是 OAuth 申請等待期間的暫代方案；介面與 PRAWScraper
一致，OAuth 過了之後 factory 切換即可。

限制：
- duplicates / user submissions：endpoint 存在但 Reddit 對未認證請求有時 403。
  失敗時記 warning 並回 []（不 raise），讓上層在 OAuth 通過前能優雅降級。
- author_karma / upvote_ratio：欄位多數能拿到，但偶有 null。
"""

from __future__ import annotations

import logging
import time
from typing import Any

import requests
from requests.exceptions import HTTPError

from .base import (
    PostPayload,
    RedditScraper,
    _detect_deleted,
    _parse_created_utc,
)

logger = logging.getLogger(__name__)

REDDIT_HOST = "https://www.reddit.com"


class RateLimited(Exception):
    """Reddit 回 429 / 503 時拋出，由呼叫端決定退避策略。"""


class PublicJSONScraper(RedditScraper):
    """Read-only scraper using Reddit's public `.json` endpoints.

    參數：
        user_agent: 必填且必須具識別性（含 username 與用途），否則 Reddit 直接 403
        min_interval_seconds: 兩次請求之間最小間隔；預設 6.5 秒（~9 QPM，留 buffer）
        timeout: 單次請求 timeout
    """

    def __init__(
        self,
        user_agent: str,
        min_interval_seconds: float = 6.5,
        timeout: float = 15.0,
    ) -> None:
        if not user_agent or "reddit_tracker" not in user_agent:
            raise ValueError(
                "user_agent 必須含 'reddit_tracker' 與你的 reddit username，"
                "例如 'reddit_tracker/0.1 by your_username'"
            )
        # NOTE: 改用 requests 而非 httpx。Reddit 的 bot 偵測對 httpx 的 TLS
        # 指紋反應不穩定（同一 UA、同一連線 r/Taiwan 過、r/tifu 403）；
        # requests 的指紋已被 Reddit 長期接受（PRAW 自己就用 requests）。
        self._session = requests.Session()
        self._session.headers.update(
            {
                "User-Agent": user_agent,
                "Accept": "application/json",
                "Accept-Language": "en-US,en;q=0.9",
            }
        )
        self._timeout = timeout
        self._min_interval = min_interval_seconds
        self._last_request_at: float = 0.0

    # ------------------------------------------------------------------
    # RedditScraper interface
    # ------------------------------------------------------------------

    def fetch_new(self, subreddit: str, limit: int = 50) -> list[PostPayload]:
        data = self._get_json(f"/r/{subreddit}/new.json", params={"limit": limit})
        return self._parse_listing(data)

    def search(
        self,
        query: str,
        subreddit: str = "all",
        time_filter: str = "day",
        limit: int = 50,
    ) -> list[PostPayload]:
        params: dict[str, Any] = {
            "q": query,
            "t": time_filter,
            "limit": limit,
            "sort": "new",
        }
        if subreddit and subreddit != "all":
            params["restrict_sr"] = "on"
            path = f"/r/{subreddit}/search.json"
        else:
            path = "/search.json"
        data = self._get_json(path, params=params)
        return self._parse_listing(data)

    def fetch_post(self, post_id: str) -> PostPayload | None:
        # /comments/<id>.json 回 [submission_listing, comments_listing]
        try:
            data = self._get_json(f"/comments/{post_id}.json")
        except HTTPError as e:
            if e.response is not None and e.response.status_code in (403, 404):
                return None
            raise
        if not isinstance(data, list) or not data:
            return None
        posts = self._parse_listing(data[0])
        return posts[0] if posts else None

    def fetch_duplicates(self, post_id: str) -> list[PostPayload]:
        try:
            data = self._get_json(f"/duplicates/{post_id}.json")
        except HTTPError as e:
            logger.warning(
                "fetch_duplicates 失敗 (post_id=%s, status=%s)；"
                "public JSON endpoint 對 duplicates 有時限制，"
                "等 OAuth 過了用 PRAWScraper 才穩定支援",
                post_id,
                e.response.status_code if e.response is not None else "?",
            )
            return []
        # duplicates response 結構：[original_listing, duplicates_listing]
        if not isinstance(data, list) or len(data) < 2:
            return []
        return self._parse_listing(data[1])

    def fetch_user_submissions(self, username: str, limit: int = 20) -> list[PostPayload]:
        try:
            data = self._get_json(
                f"/user/{username}/submitted.json",
                params={"limit": limit, "sort": "new"},
            )
        except HTTPError as e:
            logger.warning(
                "fetch_user_submissions 失敗 (user=%s, status=%s)",
                username,
                e.response.status_code if e.response is not None else "?",
            )
            return []
        return self._parse_listing(data)

    # ------------------------------------------------------------------
    # internals
    # ------------------------------------------------------------------

    def _throttle(self) -> None:
        now = time.monotonic()
        wait = self._min_interval - (now - self._last_request_at)
        if wait > 0:
            time.sleep(wait)
        self._last_request_at = time.monotonic()

    def _get_json(self, path: str, params: dict[str, Any] | None = None) -> Any:
        self._throttle()
        url = f"{REDDIT_HOST}{path}"
        resp = self._session.get(url, params=params, timeout=self._timeout)
        if resp.status_code in (429, 503):
            raise RateLimited(f"Reddit rate-limited at {url} (status={resp.status_code})")
        resp.raise_for_status()
        return resp.json()

    @staticmethod
    def _parse_listing(data: Any) -> list[PostPayload]:
        """把 Reddit Listing JSON 轉成 PostPayload 串列。"""
        if not isinstance(data, dict):
            return []
        children = data.get("data", {}).get("children", [])
        out: list[PostPayload] = []
        for child in children:
            if not isinstance(child, dict) or child.get("kind") != "t3":
                # t3 = submission；其他種類（t1=comment, t5=subreddit）跳過
                continue
            d = child.get("data") or {}
            try:
                out.append(_payload_from_dict(d))
            except (KeyError, TypeError, ValueError) as e:
                logger.debug("跳過無法解析的 submission: %s (err=%s)", d.get("id"), e)
        return out

    def close(self) -> None:
        self._session.close()


def _payload_from_dict(d: dict) -> PostPayload:
    selftext = d.get("selftext") or ""
    author = d.get("author")
    if author == "[deleted]":
        author = None
    return PostPayload(
        reddit_post_id=d["id"],
        subreddit=d.get("subreddit", ""),
        title=d.get("title", ""),
        selftext=selftext,
        author=author,
        author_karma=None,  # public JSON 不直接帶；要另外打 /user/<name>/about.json
        score=int(d.get("score", 0)),
        upvote_ratio=_safe_float(d.get("upvote_ratio")),
        num_comments=int(d.get("num_comments", 0)),
        created_utc=_parse_created_utc(float(d["created_utc"])),
        permalink=d.get("permalink", ""),
        url=d.get("url", ""),
        is_self=bool(d.get("is_self", False)),
        is_deleted=_detect_deleted(selftext, author),
        over_18=bool(d.get("over_18", False)),
        stickied=bool(d.get("stickied", False)),
        extras={
            "domain": d.get("domain"),
            "link_flair_text": d.get("link_flair_text"),
            "num_crossposts": d.get("num_crossposts"),
        },
    )


def _safe_float(v: Any) -> float | None:
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None

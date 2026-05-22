"""Public JSON endpoint scraper — no-reddit-api 路線的唯一實作。

Reddit 的 `<url>.json` 後綴對未認證請求可用，速率限制大約 10 req/min（per IP），
TOS 允許 personal / academic use。M1 probe 實測結果見
`docs/m1_public_endpoints_probe.md`：

| endpoint                       | success_rate | 備註 |
| ------------------------------ | ------------ | ---- |
| /r/<sub>/new.json              | 100%         | 主軸 discovery |
| /comments/<id>.json            | 100%         | 樹深 10 / 500 cap，MoreComments 0/9 樣本中皆為 0 |
| /r/<sub>/search.json           | 視 sub       | r/AmItheAsshole 200；r/tifu 403（疑似 NSFW 旗標）|
| /user/<name>/about.json        | 83%          | 偶有 403（shadowban / deleted）|
| /user/<name>/submitted.json    | 100%         | M5 author_followup |
| /duplicates/<id>.json          | 67%          | 偶有 403（疑似 NSFW / quarantine）|
| /search.json (all-reddit)      | **0%**       | 一律 403，不可用 |

設計取捨：
- 失敗（403 / 404）一律記 debug log + 回 None / []，不 raise，讓上層 ingest 不中斷
- HTTP 429 / 503 是 throttle 訊號 → raise RateLimited，由呼叫端決定退避
- author_about 做 24h LRU cache，同 username 一天只打一次
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any

import requests
from requests.exceptions import HTTPError

from .base import (
    CommentNode,
    PostPayload,
    RedditScraper,
    UserProfile,
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
        user_about_cache_ttl: float = 86400.0,
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
        self._user_about_cache: dict[str, tuple[float, UserProfile | None]] = {}
        self._user_about_cache_ttl = user_about_cache_ttl

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
            status = e.response.status_code if e.response is not None else None
            # probe 數據：dups endpoint 偶發 403（疑似 NSFW / quarantine）；不算錯誤
            logger.debug("fetch_duplicates(post_id=%s) status=%s, treat as empty", post_id, status)
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
            status = e.response.status_code if e.response is not None else None
            logger.debug("fetch_user_submissions(user=%s) status=%s, treat as empty",
                         username, status)
            return []
        return self._parse_listing(data)

    def fetch_user_about(self, username: str) -> UserProfile | None:
        """`/user/<name>/about.json` — 拿 link_karma + comment_karma + created_utc。

        對同一 username 在 `user_about_cache_ttl` 秒內只打一次 endpoint。
        負面結果（None）也會 cache，避免對 shadowbanned 帳號重複試。
        """
        now = time.monotonic()
        cached = self._user_about_cache.get(username)
        if cached and (now - cached[0]) < self._user_about_cache_ttl:
            return cached[1]

        try:
            data = self._get_json(f"/user/{username}/about.json")
        except HTTPError as e:
            status = e.response.status_code if e.response is not None else None
            logger.debug("fetch_user_about(%s) status=%s, treat as missing", username, status)
            self._user_about_cache[username] = (now, None)
            return None

        if not isinstance(data, dict):
            self._user_about_cache[username] = (now, None)
            return None
        d = (data.get("data") or {})
        created_ts = d.get("created_utc")
        profile = UserProfile(
            username=username,
            link_karma=_safe_int(d.get("link_karma")),
            comment_karma=_safe_int(d.get("comment_karma")),
            created_utc=(
                datetime.fromtimestamp(float(created_ts), tz=timezone.utc)
                if created_ts is not None
                else None
            ),
        )
        self._user_about_cache[username] = (now, profile)
        return profile

    def fetch_comment_tree(
        self, post_id: str, *, limit: int = 500, depth: int = 10
    ) -> list[CommentNode]:
        """`/comments/<id>.json?limit=L&depth=D` — 拿留言樹並攤平成扁平 list。

        Reddit 回 [submission_listing, comments_listing]；只關心後者。
        submission.author 從 listing 0 拿，用於標記 is_submitter。
        """
        try:
            data = self._get_json(
                f"/comments/{post_id}.json",
                params={"limit": limit, "depth": depth},
            )
        except HTTPError as e:
            status = e.response.status_code if e.response is not None else None
            logger.debug("fetch_comment_tree(%s) status=%s, treat as empty",
                         post_id, status)
            return []
        if not isinstance(data, list) or len(data) < 2:
            return []

        # 從 submission listing 拿 author（用於標 is_submitter）
        submitter = None
        sub_children = data[0].get("data", {}).get("children", []) if isinstance(data[0], dict) else []
        if sub_children:
            d = sub_children[0].get("data") or {}
            submitter = d.get("author") if d.get("author") != "[deleted]" else None

        # 攤平
        comment_children = data[1].get("data", {}).get("children", []) if isinstance(data[1], dict) else []
        flat: list[CommentNode] = []
        _flatten_comments(comment_children, parent_id=f"t3_{post_id}",
                          submitter=submitter, depth=0, out=flat)
        return flat

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


def _safe_int(v: Any) -> int | None:
    try:
        return int(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def _flatten_comments(
    children: list,
    *,
    parent_id: str,
    submitter: str | None,
    depth: int,
    out: list[CommentNode],
) -> None:
    """Reddit comment listing → flatten 成 CommentNode list（DFS pre-order）。

    `parent_id` 對最上層是 t3_<post>，對巢狀回覆是上一層 t1_<comment>。
    `kind=more` 節點轉為 placeholder，記下 omitted_count 給上層提示 "more shown" 用。
    """
    for c in children:
        if not isinstance(c, dict):
            continue
        kind = c.get("kind")
        d = c.get("data") or {}
        if kind == "more":
            out.append(
                CommentNode(
                    comment_id=d.get("id", ""),
                    parent_id=parent_id,
                    author=None,
                    body="",
                    score=0,
                    created_utc=datetime.fromtimestamp(0, tz=timezone.utc),
                    depth=depth,
                    is_submitter=False,
                    is_more_placeholder=True,
                    omitted_count=_safe_int(d.get("count")) or 0,
                )
            )
            continue
        if kind != "t1":
            continue
        author = d.get("author")
        if author == "[deleted]":
            author = None
        try:
            created = _parse_created_utc(float(d.get("created_utc", 0)))
        except (TypeError, ValueError):
            created = datetime.fromtimestamp(0, tz=timezone.utc)
        cid = d.get("id", "")
        out.append(
            CommentNode(
                comment_id=cid,
                parent_id=parent_id,
                author=author,
                body=d.get("body") or "",
                score=_safe_int(d.get("score")) or 0,
                created_utc=created,
                depth=depth,
                is_submitter=bool(submitter and author == submitter),
            )
        )
        replies = d.get("replies")
        if isinstance(replies, dict):
            _flatten_comments(
                replies.get("data", {}).get("children", []),
                parent_id=f"t1_{cid}",
                submitter=submitter,
                depth=depth + 1,
                out=out,
            )

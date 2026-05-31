"""RSS scraper — Plan C fallback after Reddit deprecated anonymous .json endpoints.

2026-05-29 起 Reddit 把 anonymous .json endpoint 全擋（403），但 RSS feed 仍開放。
本 scraper 走 `/r/<sub>/new/.rss` 與 `/user/<u>/submitted/.rss` 兩個 endpoint，
等 Data Access Request OAuth 通過後再切回 PRAW。

RSS payload vs .json 缺什麼：
- 無 score / num_comments / upvote_ratio
- 無 author_karma / account_created_utc
- 無 stickied / distinguished / over_18
- 有 title / selftext (HTML escaped) / author / permalink / created_utc / post_id

對應 scoring：
- 規則 1（interaction velocity）：score==0 且 num_comments==0 → 視為 unknown 放行
- 規則 2/3（karma / account_age）：本來就 None → 放行（既有 fallback 邏輯）
- 規則 4/5/6（長度 / 語言 / 黑名單）：input 不變，照跑

Plan C 支援的 abstract method：
- fetch_new                ✅ `/r/<sub>/new/.rss`
- fetch_user_submissions   ✅ `/user/<u>/submitted/.rss`
- 其餘 5 個 method 全 raise NotImplementedError（keyword discovery / detection /
  duplicates / comment tree / user about 在 Plan C 階段 disable，
  上層 scheduler job 內 try/except 接住、log warning 後繼續）
"""

from __future__ import annotations

import logging
import re
import time
from datetime import datetime, timezone
from html import unescape
from xml.etree import ElementTree as ET

import requests
from requests.exceptions import HTTPError

from .base import (
    CommentNode,
    PostPayload,
    RedditScraper,
    UserProfile,
)

logger = logging.getLogger(__name__)

REDDIT_HOST = "https://www.reddit.com"
ATOM_NS = "{http://www.w3.org/2005/Atom}"
POST_ID_PREFIX = "t3_"

# Reddit RSS 把 selftext HTML 包在 <!-- SC_OFF --> ... <!-- SC_ON --> 之間，
# 後面接 "submitted by /u/xxx [link] [comments]" 樣板。
TAG_RE = re.compile(r"<[^>]+>")
SUBMITTED_BY_RE = re.compile(r"submitted\s+by.*", re.IGNORECASE | re.DOTALL)


class RssScraper(RedditScraper):
    """Read-only scraper using Reddit RSS / Atom feeds.

    與 PublicJSONScraper 同樣抽象介面，主要差別：
    - 只實作 fetch_new + fetch_user_submissions，其他 raise NotImplementedError
    - PostPayload.score / num_comments 一律 0；extras={"source": "rss"} 供
      scoring 判斷是否走 unknown-engagement 路徑
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
        self._session = requests.Session()
        self._session.headers.update(
            {
                "User-Agent": user_agent,
                "Accept": "application/atom+xml,application/xml,text/xml;q=0.9",
                "Accept-Language": "en-US,en;q=0.9",
            }
        )
        self._timeout = timeout
        self._min_interval = min_interval_seconds
        self._last_request_at: float = 0.0
        self._search_warned = False

    # ------------------------------------------------------------------
    # RedditScraper interface
    # ------------------------------------------------------------------

    def fetch_new(self, subreddit: str, limit: int = 50) -> list[PostPayload]:
        xml_text = self._get_rss(f"/r/{subreddit}/new/.rss", params={"limit": limit})
        if xml_text is None:
            return []
        return self._parse_feed(xml_text, default_subreddit=subreddit)

    def search(
        self,
        query: str,
        subreddit: str = "all",
        time_filter: str = "day",
        limit: int = 50,
    ) -> list[PostPayload]:
        # Plan C 階段 keyword_discovery 暫停. 為避免 service 層每 (keyword, sub)
        # 組合各 noisy 一次, 改成 return [] + 一次性 warn — keyword job 整輪
        # silent fail 寫成 "inserted=0", 跟 OAuth 通了切回 PRAW 即恢復.
        if not self._search_warned:
            logger.warning(
                "RssScraper.search() called: Reddit RSS 無 search endpoint, "
                "Plan C 階段 keyword_discovery 全部回 []. "
                "OAuth (PRAW) 通了切回即恢復."
            )
            self._search_warned = True
        return []

    def fetch_post(self, post_id: str) -> PostPayload | None:
        raise NotImplementedError(
            "Reddit RSS 無 single-post endpoint；M5 detection 邏輯需走 OAuth 路徑。"
        )

    def fetch_duplicates(self, post_id: str) -> list[PostPayload]:
        raise NotImplementedError(
            "Reddit RSS 無 duplicates endpoint；crosspost 偵測需走 OAuth。"
        )

    def fetch_user_submissions(
        self, username: str, limit: int = 20
    ) -> list[PostPayload]:
        xml_text = self._get_rss(
            f"/user/{username}/submitted/.rss", params={"limit": limit}
        )
        if xml_text is None:
            return []
        return self._parse_feed(xml_text, default_subreddit=None)

    def fetch_user_about(self, username: str) -> UserProfile | None:
        raise NotImplementedError(
            "Reddit RSS 無 user about endpoint；karma / account_age 拿不到。"
        )

    def fetch_comment_tree(
        self, post_id: str, *, limit: int = 500, depth: int = 10
    ) -> list[CommentNode]:
        raise NotImplementedError(
            "Reddit RSS 無 comment tree endpoint；M6 問答需 OAuth。"
        )

    def close(self) -> None:
        self._session.close()

    # ------------------------------------------------------------------
    # internals
    # ------------------------------------------------------------------

    def _throttle(self) -> None:
        elapsed = time.monotonic() - self._last_request_at
        if elapsed < self._min_interval:
            time.sleep(self._min_interval - elapsed)
        self._last_request_at = time.monotonic()

    def _get_rss(self, path: str, params: dict | None = None) -> str | None:
        self._throttle()
        url = f"{REDDIT_HOST}{path}"
        try:
            resp = self._session.get(
                url, params=params or {}, timeout=self._timeout
            )
            resp.raise_for_status()
            return resp.text
        except HTTPError as e:
            status = e.response.status_code if e.response is not None else None
            logger.warning("RSS fetch %s status=%s", path, status)
            return None
        except requests.RequestException as e:
            logger.warning("RSS fetch %s error: %s", path, e)
            return None

    def _parse_feed(
        self, xml_text: str, *, default_subreddit: str | None
    ) -> list[PostPayload]:
        try:
            root = ET.fromstring(xml_text)
        except ET.ParseError as e:
            logger.warning("RSS parse error: %s", e)
            return []
        posts: list[PostPayload] = []
        for entry in root.findall(f"{ATOM_NS}entry"):
            post = self._parse_entry(entry, default_subreddit=default_subreddit)
            if post:
                posts.append(post)
        return posts

    def _parse_entry(
        self, entry: ET.Element, *, default_subreddit: str | None
    ) -> PostPayload | None:
        id_text = (entry.findtext(f"{ATOM_NS}id") or "").strip()
        if not id_text.startswith(POST_ID_PREFIX):
            return None
        reddit_post_id = id_text[len(POST_ID_PREFIX):]

        title = (entry.findtext(f"{ATOM_NS}title") or "").strip()

        author = None
        author_name_el = entry.find(f"{ATOM_NS}author/{ATOM_NS}name")
        if author_name_el is not None and author_name_el.text:
            raw = author_name_el.text.strip()
            author = raw[3:] if raw.startswith("/u/") else raw

        subreddit = default_subreddit or ""
        cat_el = entry.find(f"{ATOM_NS}category")
        if cat_el is not None:
            term = cat_el.get("term")
            if term:
                subreddit = term

        permalink = ""
        url = ""
        link_el = entry.find(f"{ATOM_NS}link")
        if link_el is not None:
            full = link_el.get("href") or ""
            url = full
            if full.startswith(REDDIT_HOST):
                permalink = full[len(REDDIT_HOST):]
            else:
                permalink = full

        published = entry.findtext(f"{ATOM_NS}published") or entry.findtext(
            f"{ATOM_NS}updated"
        )
        try:
            if published:
                created_utc = datetime.fromisoformat(published).astimezone(timezone.utc)
            else:
                created_utc = datetime.now(timezone.utc)
        except (ValueError, TypeError):
            created_utc = datetime.now(timezone.utc)

        content_el = entry.find(f"{ATOM_NS}content")
        selftext = ""
        if content_el is not None and content_el.text:
            selftext = self._extract_selftext(content_el.text)

        return PostPayload(
            reddit_post_id=reddit_post_id,
            subreddit=subreddit,
            title=title,
            selftext=selftext,
            author=author,
            author_karma=None,
            score=0,
            upvote_ratio=None,
            num_comments=0,
            created_utc=created_utc,
            permalink=permalink,
            url=url,
            is_self=bool(selftext),
            is_deleted=False,
            over_18=False,
            stickied=False,
            extras={"source": "rss"},
        )

    @staticmethod
    def _extract_selftext(html: str) -> str:
        """RSS <content> 是 HTML escaped；去 tag、去尾巴的 'submitted by ...' 樣板。"""
        s = unescape(html)
        s = SUBMITTED_BY_RE.sub("", s)
        s = TAG_RE.sub("", s)
        # 多餘空白合併
        return re.sub(r"\s+", " ", s).strip()

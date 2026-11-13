"""desk-v3 D2：抓文章頁、抽正文，存進 `item_fulltext`（設計見 docs/pr/desk-v3.md「D 階段設計」）。

預設關閉（`FULLTEXT_ENABLED=false`），也還沒接上收集排程；`fetch_pending` 只能由人工或之後的
排程呼叫。測試一律注入 `get`，不實際連網。

規則摘要：
- 只抓登錄表網域；redirect 不自動跟，手動跟最多 `MAX_REDIRECTS` 次，每一跳都檢查網域。
- robots.txt 每網域讀一次；4xx 視為允許，5xx／網路錯誤視為不允許。
- 不繞付費牆：`FULLTEXT_SKIP_DOMAINS`、HTTP 401/402/403 → `paywalled`；正文太短 → `too_short`。
- 每篇只抓一次（表裡有任何狀態就跳過），同網域請求間隔、單次上限可設。
- 正文去掉零寬／控制字元，`<<<`、`>>>` 改全形，避免偽造證據分隔。
"""

from __future__ import annotations

import hashlib
import logging
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from html.parser import HTMLParser
from typing import Callable, Iterable
from urllib.parse import urljoin, urlsplit
from urllib.robotparser import RobotFileParser

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import ItemFulltext, SourceItem
from .clustering import domain_of
from .collector import USER_AGENT

log = logging.getLogger(__name__)

EXTRACTOR = "stdlib-html/1"
FETCH_TIMEOUT_SECONDS = 10.0
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
MAX_REDIRECTS = 3
HTML_TYPES = ("text/html", "application/xhtml+xml")
PAYWALL_STATUSES = frozenset({401, 402, 403})
STATUSES = (
    "ok", "robots_denied", "paywalled", "too_short", "http_error", "non_html", "blocked_domain", "error",
)

_SKIP_TAGS = frozenset({
    "script", "style", "noscript", "nav", "header", "footer", "aside", "form", "iframe", "svg",
    "button", "select", "template",
})
_BLOCK_TAGS = frozenset({"p", "h2", "h3", "li", "blockquote"})
_VOID_TAGS = frozenset({
    "area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr",
})
_INVISIBLE_RE = re.compile("[​-‏‪-‮⁠-⁤﻿\x00-\x08\x0b-\x1f\x7f]")
_SPACE_RE = re.compile(r"[ \t\r\f\v 　]+")


@dataclass
class HttpResponse:
    """`get` 的回傳；`body` 已依 `MAX_RESPONSE_BYTES` 截斷。"""

    status_code: int
    url: str
    headers: dict[str, str]
    body: bytes

    @property
    def content_type(self) -> str:
        for key, value in self.headers.items():
            if key.lower() == "content-type":
                return value.split(";", 1)[0].strip().lower()
        return ""

    @property
    def location(self) -> str | None:
        for key, value in self.headers.items():
            if key.lower() == "location":
                return value
        return None

    def text(self) -> str:
        charset = "utf-8"
        for key, value in self.headers.items():
            if key.lower() == "content-type" and "charset=" in value.lower():
                charset = value.lower().split("charset=", 1)[1].split(";", 1)[0].strip() or "utf-8"
        try:
            return self.body.decode(charset, errors="replace")
        except LookupError:
            return self.body.decode("utf-8", errors="replace")


Getter = Callable[[str], HttpResponse]


@dataclass
class FetchResult:
    status: str
    http_status: int | None = None
    final_url: str | None = None
    text: str | None = None
    error: str | None = None


# --- 抽取 ---------------------------------------------------------------


class _Collector(HTMLParser):
    """收 `<article>`、`<main>`、全頁三層的段落文字，略過導覽、腳本等。"""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._stack: list[str] = []
        self._skip = 0
        self._article = 0
        self._main = 0
        self._block: list[str] | None = None
        self.blocks: dict[str, list[str]] = {"article": [], "main": [], "page": []}

    def handle_starttag(self, tag, attrs):
        if tag in _VOID_TAGS:
            if tag == "br" and self._block is not None:
                self._block.append(" ")
            return
        self._stack.append(tag)
        if tag in _SKIP_TAGS:
            self._skip += 1
        elif tag == "article":
            self._article += 1
        elif tag == "main":
            self._main += 1
        elif tag in _BLOCK_TAGS and self._skip == 0 and self._block is None:
            self._block = []

    def handle_endtag(self, tag):
        if tag in _VOID_TAGS or tag not in self._stack:
            return
        while self._stack:
            open_tag = self._stack.pop()
            self._close(open_tag)
            if open_tag == tag:
                break

    def _close(self, tag: str) -> None:
        if tag in _SKIP_TAGS:
            self._skip = max(0, self._skip - 1)
        elif tag == "article":
            self._article = max(0, self._article - 1)
        elif tag == "main":
            self._main = max(0, self._main - 1)
        elif tag in _BLOCK_TAGS and self._block is not None:
            text = _SPACE_RE.sub(" ", "".join(self._block)).strip()
            self._block = None
            if text:
                self.blocks["page"].append(text)
                if self._main:
                    self.blocks["main"].append(text)
                if self._article:
                    self.blocks["article"].append(text)

    def handle_data(self, data):
        if self._skip == 0 and self._block is not None:
            self._block.append(data)

    def close(self):
        super().close()
        while self._stack:
            self._close(self._stack.pop())


def sanitize_text(text: str) -> str:
    """去零寬／控制字元，`<<<`／`>>>` 改全形，避免全文偽造 `<<<S1>>>` 分隔。"""
    text = _INVISIBLE_RE.sub("", text)
    return text.replace("<<<", "＜＜＜").replace(">>>", "＞＞＞")


def extract(html: str) -> str:
    """抽正文：有 `<article>` 用它，其次 `<main>`，再退回全頁；段落之間空一行。"""
    parser = _Collector()
    try:
        parser.feed(html)
        parser.close()
    except Exception:  # noqa: BLE001 — 壞 HTML 就當抽不到
        return ""
    for scope in ("article", "main", "page"):
        blocks = parser.blocks[scope]
        if blocks:
            return sanitize_text("\n\n".join(blocks)).strip()
    return ""


# --- robots.txt ---------------------------------------------------------


class RobotsCache:
    """每個 scheme+host 讀一次 robots.txt。"""

    def __init__(self, get: Getter, user_agent: str = USER_AGENT) -> None:
        self._get = get
        self._user_agent = user_agent
        self._cache: dict[str, RobotFileParser | bool] = {}

    def allowed(self, url: str) -> bool:
        parts = urlsplit(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        if origin not in self._cache:
            self._cache[origin] = self._load(origin)
        entry = self._cache[origin]
        if isinstance(entry, bool):
            return entry
        return entry.can_fetch(self._user_agent, url)

    def _load(self, origin: str) -> RobotFileParser | bool:
        try:
            resp = self._get(f"{origin}/robots.txt")
        except Exception:  # noqa: BLE001
            return False
        if 400 <= resp.status_code < 500:
            return True
        if resp.status_code != 200:
            return False
        parser = RobotFileParser()
        parser.parse(resp.text().splitlines())
        return parser


# --- 單篇抓取 -----------------------------------------------------------


def _domain_ok(url: str, allowed_domains: frozenset[str]) -> bool:
    if urlsplit(url).scheme not in ("http", "https"):
        return False
    return domain_of(url) in allowed_domains


def fetch_fulltext(
    url: str,
    *,
    get: Getter,
    robots: RobotsCache,
    allowed_domains: frozenset[str],
    skip_domains: frozenset[str] = frozenset(),
    min_chars: int = 200,
    store_max_chars: int = 20000,
) -> FetchResult:
    """抓一篇並抽正文。不丟例外，失敗都寫在 `status`／`error`。"""
    current = url
    try:
        for _ in range(MAX_REDIRECTS + 1):
            if not _domain_ok(current, allowed_domains):
                return FetchResult("blocked_domain", final_url=current)
            if domain_of(current) in skip_domains:
                return FetchResult("paywalled", final_url=current)
            if not robots.allowed(current):
                return FetchResult("robots_denied", final_url=current)
            resp = get(current)
            if resp.status_code in (301, 302, 303, 307, 308) and resp.location:
                current = urljoin(current, resp.location)
                continue
            break
        else:
            return FetchResult("http_error", final_url=current, error="too many redirects")
        if resp.status_code in PAYWALL_STATUSES:
            return FetchResult("paywalled", http_status=resp.status_code, final_url=current)
        if resp.status_code != 200:
            return FetchResult("http_error", http_status=resp.status_code, final_url=current)
        if resp.content_type not in HTML_TYPES:
            return FetchResult("non_html", http_status=200, final_url=current, error=resp.content_type or None)
        text = extract(resp.text())
        if len(text) < min_chars:
            return FetchResult("too_short", http_status=200, final_url=current)
        return FetchResult("ok", http_status=200, final_url=current, text=text[:store_max_chars])
    except Exception as exc:  # noqa: BLE001
        return FetchResult("error", final_url=current, error=f"{type(exc).__name__}: {exc}"[:500])


def requests_getter(timeout: float = FETCH_TIMEOUT_SECONDS, max_bytes: int = MAX_RESPONSE_BYTES) -> Getter:
    """正式用的 getter（不跟 redirect、讀到上限就停）。測試不要用它。"""
    import requests

    def get(url: str) -> HttpResponse:
        with requests.get(
            url, headers={"User-Agent": USER_AGENT}, timeout=timeout, allow_redirects=False, stream=True,
        ) as resp:
            body = b""
            for chunk in resp.iter_content(65536):
                body += chunk
                if len(body) >= max_bytes:
                    body = body[:max_bytes]
                    break
            return HttpResponse(resp.status_code, resp.url, dict(resp.headers), body)

    return get


# --- 批次 ---------------------------------------------------------------


def _csv_set(value: str) -> frozenset[str]:
    return frozenset(part.strip().lower() for part in value.split(",") if part.strip())


def fetch_pending(
    session: Session,
    item_ids: Iterable[int],
    *,
    allowed_domains: frozenset[str],
    get: Getter | None = None,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
    now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    settings=None,
) -> list[ItemFulltext]:
    """替還沒抓過的素材抓全文並寫進 `item_fulltext`（呼叫端 commit）。

    `FULLTEXT_ENABLED` 關閉時什麼都不做、回空清單。每篇只抓一次；同網域間隔
    `FULLTEXT_DOMAIN_INTERVAL_SECONDS`，單次最多 `FULLTEXT_MAX_PER_RUN` 篇。
    """
    settings = settings or get_settings()
    if not settings.fulltext_enabled:
        return []
    ids = list(dict.fromkeys(int(i) for i in item_ids))
    if not ids:
        return []
    done = set(session.scalars(select(ItemFulltext.item_id).where(ItemFulltext.item_id.in_(ids))).all())
    items = [
        item for item in session.scalars(select(SourceItem).where(SourceItem.id.in_(ids))).all()
        if item.id not in done
    ]
    order = {item_id: n for n, item_id in enumerate(ids)}
    items.sort(key=lambda item: order[item.id])
    get = get or requests_getter()
    robots = RobotsCache(get)
    skip = _csv_set(settings.fulltext_skip_domains)
    interval = max(0.0, float(settings.fulltext_domain_interval_seconds))
    last_hit: dict[str, float] = {}
    rows: list[ItemFulltext] = []
    for item in items[: max(0, settings.fulltext_max_per_run)]:
        url = item.url or item.canonical_url
        domain = domain_of(url)
        if domain in last_hit:
            wait = interval - (clock() - last_hit[domain])
            if wait > 0:
                sleep(wait)
        result = fetch_fulltext(
            url, get=get, robots=robots, allowed_domains=allowed_domains, skip_domains=skip,
            min_chars=settings.fulltext_min_chars, store_max_chars=settings.fulltext_store_max_chars,
        )
        last_hit[domain] = clock()
        text = result.text if result.status == "ok" else None
        row = ItemFulltext(
            item_id=item.id,
            status=result.status,
            http_status=result.http_status,
            final_url=result.final_url,
            text=text,
            text_chars=len(text) if text else 0,
            content_sha1=hashlib.sha1(text.encode("utf-8")).hexdigest() if text else None,
            extractor=EXTRACTOR,
            fetched_at=now(),
            error=result.error,
        )
        session.add(row)
        rows.append(row)
        log.info("fulltext item=%s status=%s chars=%s", item.id, result.status, row.text_chars)
    session.flush()
    return rows


def fulltext_of(session: Session, item_ids: Iterable[int]) -> dict[int, str]:
    """`status=ok` 的全文，給 D3 證據包用；沒有就不在 dict 裡（呼叫端退回摘要）。"""
    ids = [int(i) for i in item_ids if i is not None]
    if not ids:
        return {}
    rows = session.scalars(
        select(ItemFulltext).where(ItemFulltext.item_id.in_(ids), ItemFulltext.status == "ok")
    ).all()
    return {row.item_id: row.text for row in rows if row.text}

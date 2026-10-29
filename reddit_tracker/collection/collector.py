"""抓取到期的 RSS／RSSHub 來源並寫入 source_items 與 source_fetch_runs。

HTTP 與 feed 解析在 thread pool 並行；DB 寫入在呼叫端 thread 依來源逐一
commit，讓 SQLite 只有一個 writer，也讓單一來源失敗不影響其他來源。
"""

from __future__ import annotations

import calendar
import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Callable

import feedparser
import requests
from sqlalchemy import and_, false, func, or_, select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import SourceFetchRun, SourceItem
from ..seeds.news_sources import NewsSource, SourceRegistry
from .normalize import (
    canonicalize_url,
    clean_summary,
    item_key,
    resolve_published_at,
    title_fingerprint,
)

logger = logging.getLogger(__name__)

COLLECTABLE_METHODS = ("rss", "rsshub")
USER_AGENT = "Mozilla/5.0 (compatible; reddit_tracker-newsroom/0.2; +news collection)"
TIMEOUT_SECONDS = {"rsshub": 90.0}
DEFAULT_TIMEOUT_SECONDS = 30.0
TITLE_DUPLICATE_WINDOW = timedelta(hours=72)
MAX_WORKERS = 8
_KEY_RE = re.compile(r"key=[0-9A-Za-z]+")


@dataclass
class FetchedEntry:
    url: str
    guid: str | None = None
    title: str | None = None
    summary: str | None = None
    published: datetime | None = None
    author: str | None = None
    categories: list[str] = field(default_factory=list)


@dataclass
class FetchOutcome:
    started_at: datetime
    ok: bool
    http_status: int | None = None
    not_modified: bool = False
    entries: list[FetchedEntry] = field(default_factory=list)
    etag: str | None = None
    last_modified: str | None = None
    error: str | None = None
    elapsed_ms: int = 0


@dataclass
class SourceCollectStats:
    source_id: str
    ok: bool
    returned: int
    new: int
    duplicate: int
    error: str | None = None


Fetcher = Callable[[NewsSource, "SourceFetchRun | None"], FetchOutcome]


def as_utc(dt: datetime) -> datetime:
    """SQLite 讀回的 DateTime 不帶時區；本層一律以 UTC 寫入。"""
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _parse_entries(body: bytes) -> list[FetchedEntry]:
    feed = feedparser.parse(body)
    if not feed.entries and getattr(feed, "bozo", False):
        raise ValueError(f"feed 無法解析：{getattr(feed, 'bozo_exception', '')}")
    entries = []
    for raw in feed.entries:
        link = raw.get("link")
        if not link:
            continue
        parsed = raw.get("published_parsed") or raw.get("updated_parsed")
        entries.append(
            FetchedEntry(
                url=link,
                guid=raw.get("id") or None,
                title=(raw.get("title") or "").strip() or None,
                summary=raw.get("summary"),
                published=(
                    datetime.fromtimestamp(calendar.timegm(parsed), tz=timezone.utc)
                    if parsed
                    else None
                ),
                author=raw.get("author"),
                categories=[tag.get("term") for tag in raw.get("tags", []) if tag.get("term")],
            )
        )
    return entries


def fetch_source(source: NewsSource, previous: SourceFetchRun | None) -> FetchOutcome:
    settings = get_settings()
    started_at = datetime.now(timezone.utc)
    clock = time.monotonic()
    headers = {"User-Agent": USER_AGENT}
    if previous is not None and previous.ok:
        if previous.etag:
            headers["If-None-Match"] = previous.etag
        if previous.last_modified:
            headers["If-Modified-Since"] = previous.last_modified
    outcome = FetchOutcome(started_at=started_at, ok=False)
    try:
        resp = requests.get(
            source.request_url(settings.rsshub_base_url, settings.rsshub_access_key),
            headers=headers,
            timeout=TIMEOUT_SECONDS.get(source.method, DEFAULT_TIMEOUT_SECONDS),
        )
        outcome.http_status = resp.status_code
        if resp.status_code == 304:
            outcome.ok = outcome.not_modified = True
            outcome.etag, outcome.last_modified = previous.etag, previous.last_modified
        else:
            resp.raise_for_status()
            outcome.entries = _parse_entries(resp.content)
            outcome.ok = True
            outcome.etag = resp.headers.get("ETag")
            outcome.last_modified = resp.headers.get("Last-Modified")
    except Exception as exc:  # noqa: BLE001 — 每種失敗都要記進健康紀錄
        outcome.error = _KEY_RE.sub("key=***", f"{type(exc).__name__}: {exc}")[:500]
    outcome.elapsed_ms = int((time.monotonic() - clock) * 1000)
    return outcome


def latest_runs(session: Session) -> dict[str, SourceFetchRun]:
    newest = select(func.max(SourceFetchRun.id)).group_by(SourceFetchRun.source_id)
    runs = session.scalars(select(SourceFetchRun).where(SourceFetchRun.id.in_(newest)))
    return {run.source_id: run for run in runs}


def _is_due(source: NewsSource, previous: SourceFetchRun | None, now: datetime) -> bool:
    if previous is None:
        return True
    return as_utc(previous.started_at) + timedelta(minutes=source.interval_min) <= now


def _duplicate_root(
    session: Session, canonical: str, fingerprint: str | None, published_at: datetime
) -> int | None:
    # 標題相同還要發布時間接近：央行等機關會反覆使用「重要人事異動」這類標題，
    # 而首次抓取時 feed 會一次回傳多年舊稿，只看收錄時間會把它們誤判為重複。
    same_title = (
        and_(
            SourceItem.title_fingerprint == fingerprint,
            SourceItem.published_at.between(
                published_at - TITLE_DUPLICATE_WINDOW, published_at + TITLE_DUPLICATE_WINDOW
            ),
        )
        if fingerprint
        else false()
    )
    return session.scalar(
        select(SourceItem.id)
        .where(
            SourceItem.duplicate_of_id.is_(None),
            or_(SourceItem.canonical_url == canonical, same_title),
        )
        .order_by(SourceItem.id)
        .limit(1)
    )


def recompute_duplicates(items: list[SourceItem]) -> int:
    """用現在的 `title_fingerprint` 重算指紋與 `duplicate_of_id`，回傳重複稿篇數。

    指紋規則改了（例如去開頭標籤）只影響之後收到的新素材；重編舊資料（回歸集、
    `data/work` 複本）要在聚合前對全部素材重算一次。規則與 `store_outcome` 相同：
    依收錄順序（`first_seen_at`、id），網址相同、或指紋相同且發布時間差在
    `TITLE_DUPLICATE_WINDOW` 內，就是「先收到、本身不是重複稿」那篇裡 id 最小的重複。
    """
    by_url: dict[str, int] = {}
    by_fingerprint: dict[str, list[tuple[int, datetime]]] = {}
    duplicates = 0
    for item in sorted(items, key=lambda i: (as_utc(i.first_seen_at), i.id)):
        item.title_fingerprint = title_fingerprint(item.title)
        published = as_utc(item.published_at)
        candidates = [by_url[item.canonical_url]] if item.canonical_url in by_url else []
        candidates += [
            root
            for root, root_published in by_fingerprint.get(item.title_fingerprint or "", [])
            if abs(root_published - published) <= TITLE_DUPLICATE_WINDOW
        ]
        item.duplicate_of_id = min(candidates) if candidates else None
        if item.duplicate_of_id is None:
            by_url.setdefault(item.canonical_url, item.id)
            if item.title_fingerprint:
                by_fingerprint.setdefault(item.title_fingerprint, []).append((item.id, published))
        else:
            duplicates += 1
    return duplicates


def store_outcome(
    session: Session, source: NewsSource, outcome: FetchOutcome, now: datetime
) -> SourceCollectStats:
    new = duplicate = 0
    for entry in outcome.entries:
        canonical = canonicalize_url(entry.url)
        key = item_key(entry.guid, canonical)
        exists = session.scalar(
            select(SourceItem.id).where(
                SourceItem.source_id == source.id, SourceItem.item_key == key
            )
        )
        if exists is not None:
            continue
        fingerprint = title_fingerprint(entry.title)
        published_at, estimated = resolve_published_at(
            entry.published, now, source.time_offset_hours
        )
        root = _duplicate_root(session, canonical, fingerprint, published_at)
        session.add(
            SourceItem(
                source_id=source.id,
                section=source.section,
                tier=source.tier,
                item_key=key,
                url=entry.url,
                canonical_url=canonical,
                title=entry.title,
                summary=clean_summary(entry.summary),
                lang=source.lang,
                published_at=published_at,
                published_at_estimated=estimated,
                first_seen_at=now,
                title_fingerprint=fingerprint,
                duplicate_of_id=root,
                meta_json={"author": entry.author, "categories": entry.categories[:10]},
            )
        )
        # autoflush 關閉；同一批後面的項目要能比對到剛加入的這筆。
        session.flush()
        new += 1
        duplicate += root is not None
    session.add(
        SourceFetchRun(
            source_id=source.id,
            started_at=outcome.started_at,
            finished_at=datetime.now(timezone.utc),
            ok=outcome.ok,
            http_status=outcome.http_status,
            not_modified=outcome.not_modified,
            items_returned=len(outcome.entries),
            items_new=new,
            items_duplicate=duplicate,
            etag=outcome.etag,
            last_modified=outcome.last_modified,
            error=outcome.error,
            elapsed_ms=outcome.elapsed_ms,
        )
    )
    return SourceCollectStats(source.id, outcome.ok, len(outcome.entries), new, duplicate, outcome.error)


def collect_due_sources(
    session: Session,
    registry: SourceRegistry,
    *,
    now: datetime | None = None,
    only: set[str] | None = None,
    force: bool = False,
    fetcher: Fetcher = fetch_source,
) -> list[SourceCollectStats]:
    now = now or datetime.now(timezone.utc)
    previous = latest_runs(session)
    due = [
        source
        for source in registry.enabled()
        if source.method in COLLECTABLE_METHODS
        and (only is None or source.id in only)
        and (force or _is_due(source, previous.get(source.id), now))
    ]
    if not due:
        return []
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        outcomes = list(pool.map(lambda s: fetcher(s, previous.get(s.id)), due))
    stats = []
    for source, outcome in zip(due, outcomes):
        try:
            stats.append(store_outcome(session, source, outcome, now))
            session.commit()
        except Exception as exc:
            session.rollback()
            logger.exception("source collection store failed: %s", source.id)
            error = f"store failed: {type(exc).__name__}: {exc}"[:500]
            # 寫入失敗也要留健康紀錄，否則這個來源會在報表上看似從未抓取。
            session.add(
                SourceFetchRun(
                    source_id=source.id,
                    started_at=outcome.started_at,
                    finished_at=datetime.now(timezone.utc),
                    ok=False,
                    http_status=outcome.http_status,
                    items_returned=len(outcome.entries),
                    error=error,
                    elapsed_ms=outcome.elapsed_ms,
                )
            )
            session.commit()
            stats.append(SourceCollectStats(source.id, False, len(outcome.entries), 0, 0, error))
        if not outcome.ok:
            logger.warning("source fetch failed: %s %s", source.id, outcome.error)
    return stats

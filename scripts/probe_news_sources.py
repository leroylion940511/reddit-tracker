"""逐一實測來源登錄表中每個來源能否取得資料。

用法：
    uv run python scripts/probe_news_sources.py [--only id1,id2] [--include-disabled]
        [--out probe.json]

每個來源記錄：HTTP 狀態、筆數、有發布時間的比例、標題／連結完整率、
最新一筆距今時數、24 小時內筆數、耗時與錯誤。Reddit 來源依既有限速
序列化，避免和線上 newsroom 的收集搶額度；其他來源並行。
"""

from __future__ import annotations

import argparse
import calendar
import csv
import io
import json
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from datetime import datetime, timezone

import feedparser
import requests

from reddit_tracker.config import get_settings
from reddit_tracker.seeds.news_sources import NewsSource, load_registry

USER_AGENT = "Mozilla/5.0 (compatible; reddit_tracker-newsroom/0.2; source probe)"
TIMEOUT_SECONDS = {"rsshub": 90.0}
DEFAULT_TIMEOUT_SECONDS = 30.0
REDDIT_INTERVAL_SECONDS = 7.0
KEY_RE = re.compile(r"key=[0-9a-f]+")
MIN_VALID_TIMESTAMP = 946684800  # 2000-01-01T00:00:00Z


@dataclass
class ProbeResult:
    id: str
    name: str
    section: str
    tier: str
    method: str
    ok: bool
    status: int | None
    items: int
    dated_ratio: float | None
    complete_ratio: float | None
    newest_age_h: float | None
    items_24h: int | None
    elapsed_s: float
    error: str | None


def _redact(text: str) -> str:
    return KEY_RE.sub("key=***", text)


def _parse_feed(source: NewsSource, body: bytes, now: float) -> dict:
    feed = feedparser.parse(body)
    entries = feed.entries
    if not entries:
        reason = getattr(feed, "bozo_exception", None)
        raise ValueError(f"沒有任何項目{f'（{reason}）' if reason else ''}")
    stamps = []
    complete = 0
    for entry in entries:
        parsed = entry.get("published_parsed") or entry.get("updated_parsed")
        # 聯合新聞網等來源每則都填 1970-01-01（epoch 0），視同沒有發布時間。
        if parsed and calendar.timegm(parsed) > MIN_VALID_TIMESTAMP:
            stamps.append(calendar.timegm(parsed))
        if entry.get("title") and entry.get("link"):
            complete += 1
    newest = max(stamps) if stamps else None
    return {
        "items": len(entries),
        "dated_ratio": round(len(stamps) / len(entries), 3),
        "complete_ratio": round(complete / len(entries), 3),
        "newest_age_h": round((now - newest) / 3600, 1) if newest else None,
        "items_24h": sum(1 for s in stamps if now - s <= 86400),
    }


def _parse_json(body: bytes) -> dict:
    data = json.loads(body)
    rows = data if isinstance(data, list) else data.get("records") or data.get("data") or [data]
    if not rows:
        raise ValueError("JSON 沒有資料列")
    return {"items": len(rows)}


def _parse_csv(body: bytes) -> dict:
    rows = list(csv.reader(io.StringIO(body.decode("utf-8-sig"))))
    if len(rows) < 2:
        raise ValueError("CSV 沒有資料列")
    return {"items": len(rows) - 1}


def probe(source: NewsSource, session: requests.Session) -> ProbeResult:
    settings = get_settings()
    url = source.request_url(settings.rsshub_base_url, settings.rsshub_access_key)
    headers = {"User-Agent": settings.reddit_user_agent if source.method == "reddit" else USER_AGENT}
    started = time.monotonic()
    status = None
    metrics: dict = {"items": 0}
    error = None
    try:
        resp = session.get(
            url,
            headers=headers,
            timeout=TIMEOUT_SECONDS.get(source.method, DEFAULT_TIMEOUT_SECONDS),
        )
        status = resp.status_code
        resp.raise_for_status()
        if source.method == "json":
            metrics = _parse_json(resp.content)
        elif source.method == "csv":
            metrics = _parse_csv(resp.content)
        else:
            metrics = _parse_feed(source, resp.content, time.time())
    except Exception as exc:  # noqa: BLE001 — 探測要收集所有失敗型態
        error = _redact(f"{type(exc).__name__}: {exc}")[:300]
    return ProbeResult(
        id=source.id,
        name=source.name,
        section=source.section,
        tier=source.tier,
        method=source.method,
        ok=error is None,
        status=status,
        items=metrics.get("items", 0),
        dated_ratio=metrics.get("dated_ratio"),
        complete_ratio=metrics.get("complete_ratio"),
        newest_age_h=metrics.get("newest_age_h"),
        items_24h=metrics.get("items_24h"),
        elapsed_s=round(time.monotonic() - started, 1),
        error=error,
    )


def _probe_reddit_serially(sources: list[NewsSource], interval: float) -> list[ProbeResult]:
    session = requests.Session()
    results = []
    for index, source in enumerate(sources):
        if index:
            time.sleep(interval)
        results.append(probe(source, session))
    return results


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--only", help="逗號分隔的來源 id")
    parser.add_argument("--include-disabled", action="store_true")
    parser.add_argument("--out", help="輸出 JSON 結果路徑")
    parser.add_argument("--reddit-interval", type=float, default=REDDIT_INTERVAL_SECONDS)
    args = parser.parse_args()

    registry = load_registry()
    sources = registry.sources if args.include_disabled else registry.enabled()
    if args.only:
        wanted = set(args.only.split(","))
        sources = [s for s in sources if s.id in wanted]

    reddit = [s for s in sources if s.method == "reddit"]
    others = [s for s in sources if s.method != "reddit"]
    session = requests.Session()
    with ThreadPoolExecutor(max_workers=8) as pool:
        reddit_future = pool.submit(_probe_reddit_serially, reddit, args.reddit_interval)
        results = list(pool.map(lambda s: probe(s, session), others))
        results += reddit_future.result()

    order = {s.id: i for i, s in enumerate(registry.sources)}
    results.sort(key=lambda r: order[r.id])
    for r in results:
        mark = "OK  " if r.ok else "FAIL"
        detail = (
            f"items={r.items} 24h={r.items_24h} newest={r.newest_age_h}h"
            if r.ok
            else f"status={r.status} {r.error}"
        )
        print(f"{mark} {r.section:<14} {r.id:<28} {r.elapsed_s:>5}s {detail}")
    ok = sum(r.ok for r in results)
    print(f"\n{ok}/{len(results)} 個來源成功；生成時間 {datetime.now(timezone.utc).isoformat()}")

    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            json.dump([asdict(r) for r in results], fh, ensure_ascii=False, indent=2)
    return 0


if __name__ == "__main__":
    sys.exit(main())

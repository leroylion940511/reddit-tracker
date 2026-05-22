"""M1 公開 endpoint 可行性 probe — no-reddit-api 路線實測用。

對應 PROGRESS.md no-reddit-api 分支的 P1。目的：把「public JSON endpoint 在
M5/M6 用得到的 4 個 path 上實際成功率多少」寫成事實基準，再決定 P2 要做到多深。

被測 endpoints：
  1. /user/<name>/about.json            (拿 karma / created_utc，補 M3 硬規則)
  2. /user/<name>/submitted.json        (M5 author_followup)
  3. /duplicates/<id>.json              (M5 crosspost — v4 賣點)
  4. /comments/<id>.json?limit=500&depth=10  (M5 hot_reply / author_reply、M6 重量 context)

流程：
  1. 從 r/tifu + r/AmItheAsshole + r/Taiwan 各抓 hot 3 篇得到 9 個樣本
  2. 對每篇 post id 跑 endpoint 3, 4；對每篇 author 跑 endpoint 1, 2
  3. 統計每個 endpoint 的：success / 403 / 404 / 429 / other / parse_ok
  4. 寫 docs/m1_public_endpoints_probe.md

每次請求間 6.5s throttle（沿用 PublicJSONScraper 設定），全部約 4–5 分鐘。

用法：
    uv run python scripts/m1_public_endpoints_probe.py
"""

from __future__ import annotations

import json
import logging
import sys
import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import requests  # noqa: E402
from dotenv import load_dotenv  # noqa: E402

from reddit_tracker.scrapers.factory import build_scraper  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s | %(message)s",
)
log = logging.getLogger("probe")

REDDIT_HOST = "https://www.reddit.com"
MIN_INTERVAL = 6.5
TIMEOUT = 15.0
PROBE_SUBS = ["tifu", "AmItheAsshole", "Taiwan"]
PER_SUB = 3
REPORT_PATH = Path(__file__).resolve().parent.parent / "docs" / "m1_public_endpoints_probe.md"


@dataclass
class EndpointStat:
    name: str
    attempts: int = 0
    success: int = 0
    parse_ok: int = 0
    status_counts: Counter = field(default_factory=Counter)
    error_examples: list[str] = field(default_factory=list)
    sample_shapes: list[str] = field(default_factory=list)

    def record_http(self, status: int) -> None:
        self.attempts += 1
        self.status_counts[status] += 1
        if 200 <= status < 300:
            self.success += 1

    def record_error(self, exc: str) -> None:
        self.attempts += 1
        self.status_counts["exception"] += 1
        if len(self.error_examples) < 3:
            self.error_examples.append(exc)

    @property
    def success_rate(self) -> float:
        return (self.success / self.attempts) if self.attempts else 0.0


class Probe:
    def __init__(self, user_agent: str) -> None:
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": user_agent,
                "Accept": "application/json",
                "Accept-Language": "en-US,en;q=0.9",
            }
        )
        self._last_req = 0.0
        self.stats: dict[str, EndpointStat] = {
            "user_about": EndpointStat("user_about"),
            "user_submitted": EndpointStat("user_submitted"),
            "duplicates": EndpointStat("duplicates"),
            "comments": EndpointStat("comments"),
        }

    def throttle(self) -> None:
        wait = MIN_INTERVAL - (time.monotonic() - self._last_req)
        if wait > 0:
            time.sleep(wait)
        self._last_req = time.monotonic()

    def get(self, path: str, params: dict | None = None) -> tuple[int, Any]:
        self.throttle()
        url = f"{REDDIT_HOST}{path}"
        try:
            resp = self.session.get(url, params=params, timeout=TIMEOUT)
        except requests.RequestException as e:
            return -1, repr(e)
        try:
            body = resp.json() if resp.text else None
        except json.JSONDecodeError:
            body = resp.text[:200]
        return resp.status_code, body

    # ------------------------------------------------------------------
    # endpoint probes
    # ------------------------------------------------------------------

    def probe_user_about(self, name: str) -> None:
        s = self.stats["user_about"]
        status, body = self.get(f"/user/{name}/about.json")
        if status < 0:
            s.record_error(str(body))
            log.info("user_about(%s) exc=%s", name, body)
            return
        s.record_http(status)
        log.info("user_about(%s) status=%d", name, status)
        if status == 200 and isinstance(body, dict):
            data = body.get("data") or {}
            link = data.get("link_karma")
            comment = data.get("comment_karma")
            created = data.get("created_utc")
            ok = link is not None and created is not None
            if ok:
                s.parse_ok += 1
                if len(s.sample_shapes) < 2:
                    s.sample_shapes.append(
                        f"u/{name} link_karma={link} comment_karma={comment} "
                        f"created_utc={created}"
                    )

    def probe_user_submitted(self, name: str) -> None:
        s = self.stats["user_submitted"]
        status, body = self.get(
            f"/user/{name}/submitted.json", params={"limit": 5, "sort": "new"}
        )
        if status < 0:
            s.record_error(str(body))
            return
        s.record_http(status)
        log.info("user_submitted(%s) status=%d", name, status)
        if status == 200 and isinstance(body, dict):
            children = body.get("data", {}).get("children", [])
            s.parse_ok += 1 if children is not None else 0
            if children and len(s.sample_shapes) < 2:
                first = (children[0].get("data") or {}).get("title", "")[:80]
                s.sample_shapes.append(f"u/{name} got {len(children)} subs, top='{first}'")

    def probe_duplicates(self, post_id: str, sub: str) -> None:
        s = self.stats["duplicates"]
        status, body = self.get(f"/duplicates/{post_id}.json")
        if status < 0:
            s.record_error(str(body))
            return
        s.record_http(status)
        log.info("duplicates(%s/%s) status=%d", sub, post_id, status)
        if status == 200 and isinstance(body, list) and len(body) >= 2:
            dups = body[1].get("data", {}).get("children", [])
            s.parse_ok += 1
            if dups and len(s.sample_shapes) < 3:
                s.sample_shapes.append(f"r/{sub}/{post_id} → {len(dups)} dups")
            elif not dups and len(s.sample_shapes) < 3:
                s.sample_shapes.append(f"r/{sub}/{post_id} → 0 dups (200 但空)")

    def probe_comments(self, post_id: str, sub: str) -> None:
        s = self.stats["comments"]
        status, body = self.get(
            f"/comments/{post_id}.json", params={"limit": 500, "depth": 10}
        )
        if status < 0:
            s.record_error(str(body))
            return
        s.record_http(status)
        log.info("comments(%s/%s) status=%d", sub, post_id, status)
        if status == 200 and isinstance(body, list) and len(body) == 2:
            comments = body[1].get("data", {}).get("children", [])
            top_level = len(comments)
            # 攤平估全部留言數 + 偵測 MoreComments
            total, more = _count_comments(comments)
            s.parse_ok += 1
            if len(s.sample_shapes) < 3:
                s.sample_shapes.append(
                    f"r/{sub}/{post_id} top={top_level} total={total} MoreComments={more}"
                )


def _count_comments(children: list) -> tuple[int, int]:
    """遞迴數 comment 樹中的 t1 與 more 節點。"""
    total = 0
    more = 0
    for c in children:
        kind = c.get("kind")
        if kind == "t1":
            total += 1
            replies = (c.get("data") or {}).get("replies")
            if isinstance(replies, dict):
                sub_total, sub_more = _count_comments(
                    replies.get("data", {}).get("children", [])
                )
                total += sub_total
                more += sub_more
        elif kind == "more":
            more += 1
    return total, more


# ----------------------------------------------------------------------
# main
# ----------------------------------------------------------------------


def collect_samples(scraper) -> list:
    """從 PROBE_SUBS 各抓 PER_SUB 篇 hot post 當樣本。"""
    samples = []
    for sub in PROBE_SUBS:
        try:
            posts = scraper.fetch_new(sub, limit=20)
        except Exception as e:  # noqa: BLE001
            log.warning("fetch_new(%s) failed: %s", sub, e)
            continue
        # 挑有作者、非 deleted、num_comments > 0 的（提高 dup/comments 有料機率）
        good = [p for p in posts if p.author and not p.is_deleted and p.num_comments > 0]
        good.sort(key=lambda p: p.num_comments, reverse=True)
        samples.extend(good[:PER_SUB])
    return samples


def render_report(probe: Probe, samples: list) -> str:
    lines = [
        "# M1 Public Endpoints Probe Result",
        "",
        f"_Probe time: {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())}_",
        "",
        f"## 樣本",
        "",
        f"從 {PROBE_SUBS} 各取 hot {PER_SUB} 篇（按 num_comments 排序），"
        f"共 {len(samples)} 個 post / 同數 author。",
        "",
        "| sub | post_id | author | score | comments |",
        "| --- | ------- | ------ | ----- | -------- |",
    ]
    for p in samples:
        lines.append(
            f"| r/{p.subreddit} | {p.reddit_post_id} | u/{p.author} | "
            f"{p.score} | {p.num_comments} |"
        )

    lines.extend(["", "## 統計", "", "| endpoint | attempts | success | parse_ok | success_rate | 狀態分布 |",
                  "| -------- | -------- | ------- | -------- | ------------ | -------- |"])
    for s in probe.stats.values():
        dist = ", ".join(f"{k}={v}" for k, v in sorted(s.status_counts.items(), key=lambda x: str(x[0])))
        lines.append(
            f"| {s.name} | {s.attempts} | {s.success} | {s.parse_ok} | "
            f"{s.success_rate:.0%} | {dist} |"
        )

    lines.extend(["", "## 樣本輸出"])
    for s in probe.stats.values():
        lines.append(f"\n### {s.name}")
        if s.sample_shapes:
            for shape in s.sample_shapes:
                lines.append(f"- {shape}")
        else:
            lines.append("- (無成功樣本)")
        if s.error_examples:
            lines.append("\n錯誤樣本：")
            for e in s.error_examples:
                lines.append(f"- `{e}`")

    lines.extend([
        "",
        "## P2 建議",
        "",
        "依上表，補強策略：",
        "- `user_about` 成功率 → 決定能否補 author_karma / account_age",
        "- `duplicates` 成功率 → 決定 M5 crosspost 偵測能否走 public path",
        "- `comments` 的 MoreComments 比例 → 決定 M6 context 是否要降級",
        "- 各 endpoint 403 / 429 比例 → 決定 retry-with-jitter 是否值得做",
        "",
    ])
    return "\n".join(lines)


def main() -> int:
    load_dotenv()
    user_agent = (
        sys.argv[1] if len(sys.argv) > 1 else
        # build_scraper 也會 fallback 到 'reddit_tracker/0.1 by unknown'
        # 但這裡直接 import settings 拿 .env 的，避免 silent fallback
        __load_ua_from_settings()
    )
    log.info("probe with UA=%s", user_agent)

    scraper = build_scraper()
    log.info("collecting samples...")
    samples = collect_samples(scraper)
    if not samples:
        log.error("no samples collected — abort")
        return 1
    log.info("got %d samples", len(samples))

    probe = Probe(user_agent=user_agent)
    for i, p in enumerate(samples, 1):
        log.info("--- sample %d/%d: r/%s/%s by u/%s ---",
                 i, len(samples), p.subreddit, p.reddit_post_id, p.author)
        probe.probe_user_about(p.author)
        probe.probe_user_submitted(p.author)
        probe.probe_duplicates(p.reddit_post_id, p.subreddit)
        probe.probe_comments(p.reddit_post_id, p.subreddit)

    report = render_report(probe, samples)
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(report, encoding="utf-8")
    log.info("report → %s", REPORT_PATH)
    print()
    print(report)
    return 0


def __load_ua_from_settings() -> str:
    from reddit_tracker.config import get_settings
    return get_settings().reddit_user_agent


if __name__ == "__main__":
    raise SystemExit(main())

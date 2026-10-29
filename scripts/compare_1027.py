"""手冊步驟 3 第 8 點：10/27 前後對照（舊期＝母本 daily_articles，新期＝`data/work/1027_rebuild.db`）。

    uv run python scripts/compare_1027.py [--out docs/weekly/1027_compare.md]

兩邊都用唯讀方式開（母本 `mode=ro&immutable=1`、重編複本 `mode=ro`）。輸出：
1. 錯誤案例：用回歸集同一套條件（`tests/regression/checks.py`）分別判斷舊期與新期，不是目測。
   新期的稿件文字是步驟 3.8 真 Codex 撰稿的結果。
2. 每則稿件並排：版別、標題、來源清單（媒體｜標題）；用來源網址配對新舊稿件，標出移除（－）／新增（＋）的來源。
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "scripts")]

import pytest  # noqa: E402  回歸條件用 pytest.fail／skip 表示「找不到」「不適用」

import rebuild_1027 as rb  # noqa: E402

DEFAULT_OUT = ROOT / "docs/weekly/1027_compare.md"
FOCUS = ("E01", "E03", "E04", "E05", "E13", "E02", "E06", "E07", "E10")


@dataclass
class Article:
    section: str
    is_front: bool
    position: int
    kind: str
    headline: str
    writer: str
    sources: list[dict]


def _connect(uri: str) -> sqlite3.Connection:
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def load_articles(conn: sqlite3.Connection) -> tuple[list[sqlite3.Row], dict]:
    edition = conn.execute(
        "SELECT id, stats, html_path FROM daily_editions WHERE edition_date = ?", (rb.EDITION_DATE.isoformat(),)
    ).fetchone()
    rows = conn.execute(
        "SELECT * FROM daily_articles WHERE edition_id = ? ORDER BY is_front DESC, section, position", (edition["id"],)
    ).fetchall()
    return rows, dict(edition)


def _article(row) -> Article:
    return Article(row["section"], bool(row["is_front"]), row["position"], row["kind"], row["headline"],
                   row["writer"], json.loads(row["sources"]))


# ── 回歸條件用的版面 ────────────────────────────────────────────────────


def _story(runner, row, members: set[str], clusters=(), published=True, sources=None, key=None):
    sources = sources if sources is not None else json.loads(row["sources"])
    return runner.Story(
        key=key or f"article:{row['cluster_id']}",
        section=row["section"] if row is not None else "",
        kind=row["kind"] if row is not None else "",
        published=published,
        is_front=bool(row["is_front"]) if row is not None else False,
        sources=[{"title": s["title"], "source_id": s["source_id"], "outlet": s["outlet"]} for s in sources],
        members=members or {runner.norm_title(s["title"]) for s in sources},
        clusters=list(clusters),
        headline=row["headline"] if row is not None else None,
        deck=row["deck"] if row is not None else None,
        body=row["body"] if row is not None else None,
        why_it_matters=row["why_it_matters"] if row is not None else None,
        writer=row["writer"] if row is not None else None,
    )


def old_view(runner, conn):
    from reddit_tracker.config import get_settings
    from reddit_tracker.daily import render as render_module
    from reddit_tracker.models import DailyEdition
    from reddit_tracker.seeds.news_sources import load_registry

    rows, edition = load_articles(conn)
    stats = json.loads(edition["stats"])
    events = [_story(runner, row, set()) for row in rows]
    sections = load_registry(get_settings().news_sources_path).sections
    # 10/27 刊出時數據欄沒有延遲標示，照當時的樣子畫（與回歸集刊出版相同）
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(render_module, "market_stale", lambda market, edition_date: False)
        html = render_module.render_html(DailyEdition(edition_date=rb.EDITION_DATE, stats={"market": stats["market"]}), sections)
    return runner.EditionView("old", rb.EDITION_DATE, events, html, stats["market"]), rows


def _groups_with(cluster_id: int, groups: list[list[int]]) -> list[int]:
    ids, changed = {cluster_id}, True
    while changed:
        changed = False
        for group in groups:
            if ids & set(group) and not set(group) <= ids:
                ids |= set(group)
                changed = True
    return [cluster_id] + sorted(ids - {cluster_id})


def new_view(runner, conn, needed_titles: set[str]):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    from reddit_tracker.collection.clustering import outlet_of
    from reddit_tracker.collection.entities import load_lexicon
    from reddit_tracker.config import get_settings
    from reddit_tracker.daily import run
    from reddit_tracker.daily.evidence import title_context
    from reddit_tracker.daily.scoring import ScoredCluster, kind_for
    from reddit_tracker.models import StoryCluster
    from reddit_tracker.seeds.news_sources import load_registry

    rows, edition = load_articles(conn)
    stats = json.loads(edition["stats"])
    members: dict[int, list] = {}
    for m in conn.execute("SELECT * FROM source_items WHERE cluster_id IS NOT NULL"):
        members.setdefault(m["cluster_id"], []).append(m)
    outlet_counts = {r["id"]: r["outlet_count"] for r in conn.execute("SELECT id, outlet_count FROM story_clusters")}

    def cluster_info(cid):
        return runner.ClusterInfo(cid, outlet_counts[cid], [
            {"title": runner.norm_title(m["title"]), "outlet": outlet_of(m["canonical_url"], m["title"], m["summary"]),
             "tier": m["tier"], "duplicate_of_id": m["duplicate_of_id"]}
            for m in members.get(cid, [])
        ])

    events, covered = [], set()
    for row in rows:
        ids = _groups_with(row["cluster_id"], stats.get("merged_groups", []))
        covered |= set(ids)
        titles = {runner.norm_title(m["title"]) for cid in ids for m in members.get(cid, [])}
        events.append(_story(runner, row, titles, [cluster_info(cid) for cid in ids]))

    # 案例提到、但沒見報的事件：用同一個 story_evidence 組證據包（與回歸 runner 相同）
    wanted = {runner.norm_title(t) for t in needed_titles}
    registry = load_registry(get_settings().news_sources_path)
    engine = create_engine("sqlite://", creator=lambda: sqlite3.connect(f"file:{rb.REBUILD_DB}?mode=ro", uri=True))
    with Session(engine) as session:
        context = title_context(session, rb.NOW, load_lexicon(), registry.disabled_source_ids())
        for cid, cluster_members in sorted(members.items()):
            titles = {runner.norm_title(m["title"]) for m in cluster_members}
            if cid in covered or not titles & wanted:
                continue
            cluster = session.get(StoryCluster, cid)
            candidate = ScoredCluster(cid, cluster.section, kind_for(cluster), 0.0)
            evidence = run.story_evidence(session, candidate, registry, context).items
            story = _story(runner, None, titles, [cluster_info(cid)], published=False,
                           sources=[e.as_source() for e in evidence], key=f"event:{cid}")
            story.section, story.kind = cluster.section, candidate.kind
            events.append(story)
    engine.dispose()
    html = Path(edition["html_path"]).read_text(encoding="utf-8") if edition["html_path"] else ""
    return runner.EditionView("new", rb.EDITION_DATE, events, html, stats.get("market"), replay_misses=[]), rows, stats


# ── 判斷與輸出 ──────────────────────────────────────────────────────────


def judge(checks, key: str, case: dict, view) -> tuple[str, str]:
    try:
        problems = checks.CONDITIONS[key](case, view)
    except checks.NotApplicable as exc:
        return "—", f"不適用：{exc}"
    except (pytest.fail.Exception, pytest.skip.Exception) as exc:
        return "—", str(exc.msg if hasattr(exc, "msg") else exc)
    if problems:
        return "❌", "；".join(problems)
    return "✅", ""


def _cell(text: str) -> str:
    return (text or "").replace("|", "｜").replace("\n", " ")


def _short_outlet(name: str) -> str:
    from reddit_tracker.daily.evidence import short_outlet

    return short_outlet(name) if name else name


def _source_line(s: dict, mark: str) -> str:
    line = f"{_cell(_short_outlet(s['outlet']))}｜{_cell(s['title'])[:70]}"
    return f"{mark} {line}" if mark else line


def pair_articles(old: list[Article], new: list[Article]) -> list[tuple[Article | None, Article | None]]:
    scores = []
    for i, a in enumerate(old):
        ua = {s["url"] for s in a.sources}
        for j, b in enumerate(new):
            overlap = len(ua & {s["url"] for s in b.sources})
            if overlap:
                scores.append((overlap, i, j))
    used_old, used_new, pairs = set(), set(), {}
    for _, i, j in sorted(scores, key=lambda x: -x[0]):
        if i not in used_old and j not in used_new:
            used_old.add(i)
            used_new.add(j)
            pairs[i] = j
    result = [(old[i], new[pairs[i]] if i in pairs else None) for i in range(len(old))]
    result += [(None, b) for j, b in enumerate(new) if j not in used_new]
    return result


def _side(article: Article | None, other: Article | None, sections: dict[str, str], removed: bool) -> str:
    if article is None:
        return "（無）"
    label = ("頭版／" if article.is_front else "") + sections.get(article.section, article.section)
    other_urls = {s["url"] for s in other.sources} if other else set()
    lines = []
    for s in article.sources:
        mark = "" if s["url"] in other_urls else ("－" if removed else "＋")
        lines.append(_source_line(s, mark))
    return f"**{label}**｜{article.kind}｜{article.writer}<br>{_cell(article.headline)}<br>" + "<br>".join(lines)


def llm_summary() -> list[dict]:
    from llm_recorder import saved_records

    out = []
    for path in rb.LEDGERS:
        for r in saved_records(path):
            out.append({"ledger": path.relative_to(ROOT).as_posix(), **{k: r[k] for k in (
                "id", "role", "run_variant", "ok", "latency_ms", "request_hash", "error", "input_tokens", "output_tokens")}})
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args(argv)
    from tests.regression import checks
    from tests.regression import rebuild as runner

    from reddit_tracker.config import get_settings
    from reddit_tracker.seeds.news_sources import load_registry

    sections = load_registry(get_settings().news_sources_path).sections
    cases = [c for c in runner.load_cases() if c["is_error"]]
    needed = {t for c in cases for t in checks.referenced_titles(c)}
    old_conn = _connect(rb.snapshot_uri())
    new_conn = _connect(f"file:{rb.REBUILD_DB}?mode=ro")
    old, old_rows = old_view(runner, old_conn)
    new, new_rows, new_stats = new_view(runner, new_conn, needed)
    old_articles = [_article(r) for r in old_rows]
    new_articles = [_article(r) for r in new_rows]

    lines = [
        "# 10/27 前後對照（手冊步驟 3 第 8 點）",
        "",
        "> 由 `scripts/compare_1027.py` 產生，可重跑。舊期＝唯讀母本 `data/snapshots/2026-10-27.db` 的 10/27 `daily_articles`；"
        "新期＝`scripts/rebuild_1027.py` 在 `data/work/1027_rebuild.db` 複本上用修好的程式**一次重聚**＋重編（`--now 2026-10-27T06:00` 台北）。",
        "> **重編時不排除前幾期已刊事件**：複本刪掉了所有 `daily_editions`／`daily_articles`（舊期記錄的 cluster id 在重新編號後會指到不相干的事件）。",
        "> 新期素材只到 10/27 06:00（台北）；用的是現在的登錄表（社群來源已停用）。數據欄沿用 10/27 當期記錄的證交所數值。",
        "",
        "## 總覽",
        "",
        "| | 舊期（10/27 刊出） | 新期（重編） |",
        "| --- | --- | --- |",
        f"| 稿件數 | {len(old_articles)} | {len(new_articles)} |",
        f"| 撰稿者 | {dict(Counter(a.writer for a in old_articles))} | {dict(Counter(a.writer for a in new_articles))} |",
        f"| 種類 | {dict(Counter(a.kind for a in old_articles))} | {dict(Counter(a.kind for a in new_articles))} |",
        f"| 新期合併組 | — | 程式 {len(new_stats.get('entity_merge_groups', []))}、LLM {len(new_stats.get('llm_merge_groups', []))}、"
        f"LLM 被剔除 {len(new_stats.get('rejected_merges', []))} |",
        "",
        "## 錯誤案例（用回歸條件判斷）",
        "",
        "✅ 通過、❌ 違規、— 不適用（事件沒見報等）。新期文字條件用的是步驟 3.8 真 Codex 撰稿的稿件。"
        "回歸測試（`tests/regression`，逐輪聚合＋錄音重播）的結果另見週報。",
        "",
        "| 案例 | 到期 | 條件 | 舊期 | 新期 | 新期說明 |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for case in sorted(cases, key=lambda c: (c["case_id"] not in FOCUS, c["case_id"])):
        for key in [k for k in checks.CONDITIONS if k in case]:
            o, _ = judge(checks, key, case, old)
            n, why = judge(checks, key, case, new)
            lines.append(f"| {case['case_id']} {case['event_hint']} | {case['due'][5:]} | `{key}` | {o} | {n} | {_cell(why)[:200]} |")

    lines += [
        "",
        "## 稿件並排",
        "",
        "用來源網址配對；「－」＝新期沒有這個來源、「＋」＝新期新增的來源。每格：版別｜種類｜撰稿者、標題、來源（媒體｜標題）。",
        "",
        "| # | 舊期 | 新期 |",
        "| --- | --- | --- |",
    ]
    for n, (a, b) in enumerate(pair_articles(old_articles, new_articles), start=1):
        lines.append(f"| {n} | {_side(a, b, sections, removed=True)} | {_side(b, a, sections, removed=False)} |")

    records = llm_summary()
    lines += [
        "",
        "## 真 Codex 呼叫（`llm_records`）",
        "",
        f"共 {len(records)} 次嘗試（ok {sum(1 for r in records if r['ok'])}）。每一次 subprocess 嘗試都在複本的 `llm_records` 一列。",
        "",
        "| 帳本 | id | role | run_variant | ok | 秒 | input／output tokens | request_hash |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for r in records:
        lines.append(
            f"| `{r['ledger']}` | {r['id']} | {r['role']} | {r['run_variant']} | {'✅' if r['ok'] else '❌ ' + _cell(r['error'] or '')[:60]} | "
            f"{(r['latency_ms'] or 0) / 1000:.0f} | {r['input_tokens']}／{r['output_tokens']} | `{r['request_hash'][:12]}` |"
        )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {args.out.relative_to(ROOT)}: old={len(old_articles)} new={len(new_articles)} llm_records={len(records)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

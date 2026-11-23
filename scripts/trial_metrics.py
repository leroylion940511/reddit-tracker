"""試刊每期的指標表（手冊步驟 12、8.3）：只讀資料庫，印 Markdown。

    uv run python scripts/trial_metrics.py --db data/work/prod-copy.db --start 2026-11-09 --end 2026-11-15

數字全部來自 llm_records／agent_messages／story_versions／daily_editions，不估算。盲計錯誤數、
人工核准花的分鐘數不在資料庫裡，表上留空給人填。資料庫用唯讀方式開（mode=ro）。

「重複主稿候選」（手冊 8.3 重複主稿數）只是篩選：同一期兩篇刊出稿共用事件 cluster、共用素材，
或任一組的標題相似度 ≥ `DUP_TITLE_SIMILARITY`。是不是真的同一事件要人看，認定結果寫在
`docs/eval/exp3_results.md`。配對用事件（keeper cluster）比，不用各組自己的標題比：兩組刊同一批
事件，各比各的會讓改寫方式（中譯、保留英文名）影響數字。
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import date, datetime, timedelta, timezone
from itertools import combinations
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from reddit_tracker.collection.clustering import tokenize  # noqa: E402

TAIPEI = ZoneInfo("Asia/Taipei")
VARIANTS = ("pipeline", "mas")
#: 篩選用，偏高召回：2026-11-24 看過 11/09–11/15 的 924 對（各組 462）後定的，不是事前登記的門檻。
DUP_TITLE_SIMILARITY = 0.15


def open_ro(path: str) -> sqlite3.Connection:
    """唯讀開 SQLite。WAL 模式的離線複本沒有 -wal 時，mode=ro 可能打不開，改用 immutable（不寫任何檔）。"""
    immutable = "" if Path(f"{path}-wal").exists() else "&immutable=1"
    return sqlite3.connect(f"file:{path}?mode=ro{immutable}", uri=True)


def _taipei(text: str | None) -> str:
    if not text:
        return "—"
    stamp = datetime.fromisoformat(text)
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    return stamp.astimezone(TAIPEI).strftime("%m-%d %H:%M")


def title_similarity(a: str, b: str) -> float:
    """標題詞（中文 bigram＋英文詞）集合的 Dice 係數；斷詞沿用聚合程式。"""
    ta, tb = set(tokenize(a, "zh")), set(tokenize(b, "zh"))
    return 2 * len(ta & tb) / (len(ta) + len(tb)) if ta and tb else 0.0


def published_stories(conn: sqlite3.Connection, day: date, variant: str) -> dict[int, dict]:
    """{keeper cluster: 刊出稿的最後一版}。M 以 daily_articles 為準；P 是影子，寫了就算刊出。"""
    d = day.isoformat()
    stories = {}
    for story_id, keeper, merged, headline, sources in conn.execute(
        "SELECT s.id, s.keeper_cluster_id, s.merged_cluster_ids, v.headline, v.source_ids "
        "FROM stories s JOIN story_versions v ON v.story_id=s.id "
        "WHERE s.edition_date=? AND s.run_variant=? ORDER BY v.version", (d, variant)):
        stories[keeper] = {
            "story_id": story_id, "headline": headline, "sources": set(json.loads(sources or "[]")),
            "clusters": {keeper, *json.loads(merged or "[]")},
        }
    if variant == "mas":
        printed = {row[0] for row in conn.execute(
            "SELECT a.cluster_id FROM daily_articles a JOIN daily_editions e ON e.id=a.edition_id "
            "WHERE e.edition_date=?", (d,))}
        stories = {keeper: story for keeper, story in stories.items() if keeper in printed}
    return stories


def duplicate_candidates(conn: sqlite3.Connection, day: date) -> list[dict]:
    """同一期裡可能是同一事件的兩篇主稿（事件層級），附上哪幾組兩篇都刊了。"""
    by_variant = {v: published_stories(conn, day, v) for v in VARIANTS}
    found = []
    for a, b in combinations(sorted(set().union(*by_variant.values())), 2):
        both = {v: (s[a], s[b]) for v, s in by_variant.items() if a in s and b in s}
        if not both:
            continue
        similarity = max(title_similarity(x["headline"], y["headline"]) for x, y in both.values())
        same_cluster = any(x["clusters"] & y["clusters"] for x, y in both.values())
        shared = any(x["sources"] & y["sources"] for x, y in both.values())
        if same_cluster or shared or similarity >= DUP_TITLE_SIMILARITY:
            found.append({"clusters": (a, b), "similarity": similarity, "same_cluster": same_cluster,
                          "shared_source": shared, "stories": both})
    return found


def render_duplicates(days: list[tuple[date, list[dict]]]) -> str:
    lines = ["| 出刊日 | 事件對（cluster） | 標題相似 | 共用 cluster／素材 | P 兩篇 | M 兩篇 |", "| --- | --- | --- | --- | --- | --- |"]
    for day, pairs in days:
        for p in pairs:
            cells = ["／".join(f"{s['story_id']} {s['headline']}" for s in p["stories"][v]) if v in p["stories"] else "—"
                     for v in VARIANTS]
            hard = "是" if p["same_cluster"] or p["shared_source"] else "否"
            lines.append(f"| {day} | {p['clusters'][0]}／{p['clusters'][1]} | {p['similarity']:.2f} | {hard} "
                         f"| {cells[0]} | {cells[1]} |")
    return "\n".join(lines)


def day_metrics(conn: sqlite3.Connection, day: date) -> dict:
    d = day.isoformat()
    one = lambda sql, *args: conn.execute(sql, args).fetchone()  # noqa: E731
    edition = one("SELECT status, published_at, stats FROM daily_editions WHERE edition_date=?", d)
    stats = json.loads(edition[2] or "{}") if edition else {}
    calls = {
        variant: one(
            "SELECT count(*), coalesce(sum(ok),0), coalesce(sum(latency_ms),0)/1000, max(called_at) "
            "FROM llm_records WHERE edition_date=? AND run_variant=?", d, variant)
        for variant in ("pipeline", "mas")
    }
    written = {
        variant: one(
            "SELECT count(DISTINCT v.story_id) FROM story_versions v JOIN stories s ON s.id=v.story_id "
            "WHERE s.edition_date=? AND s.run_variant=?", d, variant)[0]
        for variant in ("pipeline", "mas")
    }
    messages = dict(conn.execute(
        "SELECT type, count(*) FROM agent_messages WHERE edition_date=? AND run_variant='mas' "
        "AND status NOT IN ('rejected','expired') GROUP BY type", (d,)))
    revised = one(
        "SELECT count(DISTINCT v.story_id) FROM story_versions v JOIN stories s ON s.id=v.story_id "
        "WHERE s.edition_date=? AND s.run_variant='mas' AND v.version>=2", d)[0]
    approved = one(
        "SELECT count(DISTINCT v.story_id), min(v.approved_at), max(v.approved_at) FROM story_versions v "
        "JOIN stories s ON s.id=v.story_id WHERE s.edition_date=? AND s.run_variant='mas' AND v.approved_by IS NOT NULL", d)
    published = edition[1] if edition else None
    duplicates = duplicate_candidates(conn, day)
    on_time = bool(approved[1] and published and approved[2] <= published)
    return {
        "date": d, "status": edition[0] if edition else "沒有這一期", "published": _taipei(published),
        "p_calls": calls["pipeline"][0], "m_calls": calls["mas"][0],
        "failed": (calls["pipeline"][0] - calls["pipeline"][1]) + (calls["mas"][0] - calls["mas"][1]),
        "p_secs": calls["pipeline"][2], "m_secs": calls["mas"][2], "ready": _taipei(calls["mas"][3]),
        "p_written": written["pipeline"], "m_written": written["mas"],
        "challenge": messages.get("CHALLENGE", 0), "hold": messages.get("HOLD", 0), "revised": revised,
        "degraded": "、".join(stats.get("degraded") or []) or "無",
        "approved": approved[0], "approved_at": _taipei(approved[2]),
        "approved_on_time": "是" if on_time else "否",
        "p_dup": sum("pipeline" in p["stories"] for p in duplicates),
        "m_dup": sum("mas" in p["stories"] for p in duplicates), "duplicates": duplicates,
    }


def render(rows: list[dict]) -> str:
    head = ("| 出刊日 | 狀態 | 發行（台北） | P 呼叫 | M 呼叫 | 失敗嘗試 | P 秒 | M 秒 | M 最後一次呼叫 | P 稿 | M 稿 "
            "| P 重複候選 | M 重複候選 "
            "| CHALLENGE | 改稿（≥v2） | HOLD | 降級 | 已核准 | 核准時間 | 發行前核准 | 核准分鐘（人填） |")
    lines = [head, "|" + " --- |" * (head.count("|") - 1)]
    for r in rows:
        lines.append(
            f"| {r['date']} | {r['status']} | {r['published']} | {r['p_calls']} | {r['m_calls']} | {r['failed']} "
            f"| {r['p_secs']} | {r['m_secs']} | {r['ready']} | {r['p_written']} | {r['m_written']} | {r['p_dup']} | {r['m_dup']} | {r['challenge']} "
            f"| {r['revised']} | {r['hold']} | {r['degraded']} | {r['approved']} | {r['approved_at']} "
            f"| {r['approved_on_time']} |  |")
    total_p, total_m = sum(r["p_calls"] for r in rows), sum(r["m_calls"] for r in rows)
    if total_p:
        lines.append(f"\nM 的呼叫次數是 P 的 {total_m / total_p:.1f} 倍（{total_m}／{total_p}）。")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--db", required=True)
    parser.add_argument("--start", type=date.fromisoformat, required=True)
    parser.add_argument("--end", type=date.fromisoformat, required=True)
    args = parser.parse_args()
    conn = open_ro(args.db)
    days = [args.start + timedelta(days=n) for n in range((args.end - args.start).days + 1)]
    rows = [day_metrics(conn, day) for day in days]
    print(render(rows))
    print("\n重複主稿候選（要人看是不是同一事件）：\n")
    print(render_duplicates([(day, row["duplicates"]) for day, row in zip(days, rows)]))


if __name__ == "__main__":
    main()

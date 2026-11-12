"""試刊每期的指標表（手冊步驟 12、8.3）：只讀資料庫，印 Markdown。

    uv run python scripts/trial_metrics.py --db data/work/prod-copy.db --start 2026-11-09 --end 2026-11-15

數字全部來自 llm_records／agent_messages／story_versions／daily_editions，不估算。盲計錯誤數、
人工核准花的分鐘數不在資料庫裡，表上留空給人填。資料庫用唯讀方式開（mode=ro）。
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

TAIPEI = ZoneInfo("Asia/Taipei")


def _taipei(text: str | None) -> str:
    if not text:
        return "—"
    stamp = datetime.fromisoformat(text)
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    return stamp.astimezone(TAIPEI).strftime("%m-%d %H:%M")


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
    }


def render(rows: list[dict]) -> str:
    head = ("| 出刊日 | 狀態 | 發行（台北） | P 呼叫 | M 呼叫 | 失敗嘗試 | P 秒 | M 秒 | M 最後一次呼叫 | P 稿 | M 稿 "
            "| CHALLENGE | 改稿（≥v2） | HOLD | 降級 | 已核准 | 核准時間 | 發行前核准 | 核准分鐘（人填） |")
    lines = [head, "|" + " --- |" * (head.count("|") - 1)]
    for r in rows:
        lines.append(
            f"| {r['date']} | {r['status']} | {r['published']} | {r['p_calls']} | {r['m_calls']} | {r['failed']} "
            f"| {r['p_secs']} | {r['m_secs']} | {r['ready']} | {r['p_written']} | {r['m_written']} | {r['challenge']} "
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
    conn = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True)
    days = [args.start + timedelta(days=n) for n in range((args.end - args.start).days + 1)]
    print(render([day_metrics(conn, day) for day in days]))


if __name__ == "__main__":
    main()

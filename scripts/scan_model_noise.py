"""掃描已存的稿有沒有混進模型雜訊（推理文字、JSON 殘渣），印 Markdown 表。只讀，不呼叫模型。

    # production DB（唯讀開啟）：試刊七期
    uv run python scripts/scan_model_noise.py --db reddit_tracker.db --start 2026-11-09 --end 2026-11-15
    # 實驗二的記者 v1（{case_id: {headline, deck, body, why_it_matters}}）
    uv run python scripts/scan_model_noise.py --json data/work/exp2/v1.json

規則在 `reddit_tracker/daily/noise.py`（保守：寧可漏報）。DB 用 `mode=ro` 開，每一版都掃，
表上標出是不是該篇最新版、狀態與是否核准，報告時可以分「刊出的」與「中間版」。沒有命中就 exit 0、印「沒有發現」。
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from reddit_tracker.daily.noise import story_noise  # noqa: E402

FIELDS = ("headline", "deck", "body", "why_it_matters")


def scan_db(conn: sqlite3.Connection, start: str, end: str, variant: str | None = None) -> list[dict]:
    sql = (
        "SELECT s.edition_date, v.run_variant, v.story_id, v.version, v.status, v.approved_by, "
        "v.headline, v.deck, v.body, v.why_it_matters, "
        "(SELECT max(w.version) FROM story_versions w WHERE w.story_id=v.story_id AND w.run_variant=v.run_variant) "
        "FROM story_versions v JOIN stories s ON s.id=v.story_id "
        "WHERE s.edition_date BETWEEN ? AND ?"
    )
    args: list = [start, end]
    if variant:
        sql += " AND v.run_variant=?"
        args.append(variant)
    rows = []
    for (day, run, story_id, version, status, approved_by, *texts, latest) in conn.execute(
            sql + " ORDER BY s.edition_date, v.story_id, v.version", args):
        hits = story_noise(dict(zip(FIELDS, texts)))
        if hits:
            rows.append({"where": f"{day} {run}", "id": story_id, "version": version, "latest": version == latest,
                         "status": status, "approved": bool(approved_by), "hits": hits})
    return rows


def scan_json(data: dict) -> list[dict]:
    rows = []
    for case_id, fields in data.items():
        hits = story_noise({name: fields.get(name) for name in FIELDS})
        if hits:
            rows.append({"where": "json", "id": case_id, "version": None, "latest": True,
                         "status": "", "approved": False, "hits": hits})
    return rows


def render(rows: list[dict]) -> str:
    if not rows:
        return "沒有發現模型雜訊。"
    lines = ["| 位置 | story／案例 | 版本 | 最新版 | 狀態 | 已核准 | 欄位 | 命中片段 |", "|" + " --- |" * 8]
    for r in rows:
        for field, hits in r["hits"].items():
            snippet = "；".join(hits).replace("|", "\\|")
            lines.append(
                f"| {r['where']} | {r['id']} | {r['version'] or '—'} | {'是' if r['latest'] else '否'} "
                f"| {r['status'] or '—'} | {'是' if r['approved'] else '否'} | {field} | {snippet} |")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--db", type=Path, help="SQLite 檔（唯讀開啟）")
    source.add_argument("--json", type=Path, help="{case_id: {headline, deck, body, why_it_matters}}")
    parser.add_argument("--start", help="出刊日起（含），--db 用")
    parser.add_argument("--end", help="出刊日迄（含），預設同 --start")
    parser.add_argument("--variant", choices=("pipeline", "mas"), help="只掃一組")
    args = parser.parse_args(argv)
    if args.db:
        if not args.start:
            parser.error("--db 要給 --start")
        conn = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True)
        try:
            rows = scan_db(conn, args.start, args.end or args.start, args.variant)
        finally:
            conn.close()
    else:
        rows = scan_json(json.loads(args.json.read_text(encoding="utf-8")))
    print(render(rows))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

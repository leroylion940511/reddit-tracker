"""查核員點名（`irrelevant_sources`）加不加當天中文片段的差別（只讀資料庫，不呼叫模型，印 Markdown）。

    uv run python scripts/eval_checker_fragments.py --db /path/to/copy.db --cases /path/to/exp2/cases.json

`FACT_CHECKER_ZH_FRAGMENTS`（佇列第 12 項 (2)）打開時，M 組查核員的程式點名多承認「與 S1 共有、當天少見
（篇數 < 5%）、至少兩段互不相連的中文片段」。這支腳本對兩批真實案例各算一次「關閉／打開」的點名：
- `tests/regression/fixtures/factcheck_1031_1101.json`：10/31、11/01 有 IRRELEVANT_SOURCE 的 10 篇（已知對錯）；
- 實驗二的 `cases.json`（25 案；N- 組都是正常稿，E-／H- 組列了真的無關的 `wrong_item_ids`）。
「當天」＝該期 `daily_snapshots.created_at`（線上 `run_mas` 拿到的時刻）；沒有對應期別的 E-／H- 案例，
用證據裡最晚的發布時間加 1 小時。
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "scripts")]

from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from reddit_tracker.collection.entities import load_lexicon, rare_shared_fragments  # noqa: E402
from reddit_tracker.daily.evidence import EvidenceItem, title_context  # noqa: E402
from reddit_tracker.daily.mas.orchestrator import irrelevant_sources  # noqa: E402
from reddit_tracker.seeds.news_sources import load_registry  # noqa: E402
from trial_metrics import open_ro  # noqa: E402

FIXTURE = ROOT / "tests" / "regression" / "fixtures" / "factcheck_1031_1101.json"


def _snapshot_times(conn) -> dict[str, datetime]:
    rows = conn.execute("SELECT edition_date, created_at FROM daily_snapshots").fetchall()
    return {day: datetime.fromisoformat(created).replace(tzinfo=timezone.utc) for day, created in rows}


def _story_dates(conn, ids: list[int]) -> dict[int, str]:
    if not ids:
        return {}
    marks = ",".join("?" * len(ids))
    return dict(conn.execute(f"SELECT id, edition_date FROM stories WHERE id IN ({marks})", ids).fetchall())


def _latest_published(items: list[EvidenceItem]) -> datetime:
    stamps = [datetime.fromisoformat(item.published_at) for item in items if item.published_at]
    return max(stamps).astimezone(timezone.utc) + timedelta(hours=1)


def cases(cases_path: str | None) -> list[dict]:
    """[{case, story_id, items, wrong(S 編號集合，None＝不知道)}]"""
    out = []
    for record in json.loads(FIXTURE.read_text(encoding="utf-8")):
        out.append({"case": f"F-{record['story_id']}", "story_id": record["story_id"],
                    "items": [EvidenceItem(**row) for row in record["evidence"]], "wrong": None})
    if cases_path:
        for case in json.loads(Path(cases_path).read_text(encoding="utf-8")):
            items = [EvidenceItem(**row) for row in case["evidence"]]
            wrong = {i for i, item in enumerate(items, start=1) if item.item_id in set(case.get("wrong_item_ids") or [])}
            story_id = int(case["case_id"][2:]) if case["case_id"].startswith("N-") else None
            out.append({"case": case["case_id"], "story_id": story_id, "items": items, "wrong": wrong})
    return out


def evaluate(conn, session, rows: list[dict]) -> list[dict]:
    lexicon = load_lexicon()
    disabled = load_registry().disabled_source_ids()
    snaps = _snapshot_times(conn)
    dates = _story_dates(conn, [row["story_id"] for row in rows if row["story_id"]])
    contexts: dict[datetime, object] = {}
    results = []
    for row in rows:
        items = row["items"]
        if len(items) < 2:
            continue
        day = dates.get(row["story_id"])
        now = snaps.get(day) if day else None
        now = now or _latest_published(items)
        if now not in contexts:
            contexts[now] = title_context(session, now, lexicon, disabled)
        context = contexts[now]
        off = {i for i, _ in irrelevant_sources(items)}
        on = {i for i, _ in irrelevant_sources(items, context)}
        entities = [lexicon.entities(item.title, (item.lang or "").startswith("zh")) for item in items]
        fragments = {i: rare_shared_fragments(entities[0], entities[i - 1], context) for i in sorted(off - on)}
        results.append({**row, "now": now, "total": context.total, "off": off, "on": on, "fragments": fragments})
    return results


def render(results: list[dict]) -> str:
    lines = ["| 案例 | 當天素材 | 關閉時點名 | 打開時點名 | 不再點名（共同片段） | 真的無關 |", "|---|---|---|---|---|---|"]
    for r in results:
        if not r["off"] and not r["on"]:
            continue
        sids = lambda s: "、".join(f"S{i}" for i in sorted(s)) or "—"  # noqa: E731
        freed = "；".join(f"S{i}：{'、'.join(f)}" for i, f in r["fragments"].items()) or "—"
        wrong = "—" if r["wrong"] is None else sids(r["wrong"])
        lines.append(f"| {r['case']} | {r['total']} | {sids(r['off'])} | {sids(r['on'])} | {freed} | {wrong} |")
    known = [r for r in results if r["wrong"] is not None]
    lost = sum(len(r["wrong"] & r["off"] - r["on"]) for r in known)
    freed_ok = sum(len((r["off"] - r["on"]) - r["wrong"]) for r in known)
    lines += ["", f"有標註的案例：打開後不再點名的真無關來源 {lost} 個；不再點名的同一事件來源 {freed_ok} 個。"]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--db", required=True, help="SQLite 複本（唯讀開）")
    parser.add_argument("--cases", help="實驗二 cases.json")
    args = parser.parse_args()
    conn = open_ro(args.db)
    engine = create_engine("sqlite://", creator=lambda: open_ro(args.db))
    with Session(engine) as session:
        print(render(evaluate(conn, session, cases(args.cases))))


if __name__ == "__main__":
    main()

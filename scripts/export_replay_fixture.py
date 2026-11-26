"""把一期的 `build_replay` 輸出存成回放 fixture，並列出和另一份 fixture 的互動數字對照。

用法（DB 一律指向 Lab 複本，不要指 production）：

    DATABASE_URL=sqlite:////Users/leroy/Documents/Developer/Lab/rt-data-1123/desk-v3-demo/demo.db \\
      REDDIT_TRACKER_NO_DOTENV=1 uv run python scripts/export_replay_fixture.py \\
      --date 2026-11-24 --out tests/fixtures/replay/2026-11-24_mas_desk_v3.json \\
      --compare tests/fixtures/replay/2026-11-19_mas.json

只讀 DB；`--compare` 只讀另一份 fixture，印出 R4 摘要卡數字對照（Markdown 表格）。
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from reddit_tracker.daily.replay import build_card, build_lanes, build_replay, build_threads

COMPARE_KEYS = (
    ("stories", "稿件數"),
    ("messages", "訊息數"),
    ("pitches", "提案"),
    ("challenges", "查核員異議"),
    ("requests", "改稿請求"),
    ("revisions", "修稿完成"),
    ("rebuts", "記者反駁"),
    ("page_objections", "版面異議"),
    ("decisions", "總編裁決"),
    ("holds", "HOLD"),
    ("llm_calls", "模型呼叫"),
    ("llm_secs", "模型耗時（秒）"),
)


def card_of(data: dict) -> dict:
    beats = data["beats"]
    return build_card(beats, build_lanes(beats, data.get("variant", "mas")), build_threads(beats))


def compare_table(base: dict, other: dict, base_name: str, other_name: str) -> str:
    a, b = card_of(base)["counts"], card_of(other)["counts"]
    rows = [f"| 項目 | {base_name} | {other_name} |", "|---|---:|---:|"]
    rows += [f"| {label} | {a.get(key, 0)} | {b.get(key, 0)} |" for key, label in COMPARE_KEYS]
    return "\n".join(rows)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", type=date.fromisoformat, required=True)
    parser.add_argument("--variant", default="mas")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--compare", type=Path, default=None, help="另一份 fixture，印出摘要卡數字對照")
    args = parser.parse_args(argv)

    from reddit_tracker.db import session_scope

    with session_scope() as session:
        data = build_replay(session, args.date, args.variant)
    if not data["beats"]:
        raise SystemExit(f"{args.date} {args.variant} 沒有回放資料")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(data, ensure_ascii=False, indent=1, default=str) + "\n", encoding="utf-8")
    print(f"wrote {args.out} beats={len(data['beats'])} stories={len(data['stories'])}")
    if args.compare:
        base = json.loads(args.compare.read_text(encoding="utf-8"))
        print(compare_table(base, data, base["date"], data["date"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

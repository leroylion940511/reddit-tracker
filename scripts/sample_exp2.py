"""從有寫正文的 M 組稿用固定種子抽 25 篇，給標註員 A 挑 15 篇正常稿。

    uv run python scripts/sample_exp2.py --dates 2026-11-09,2026-11-10

第一行是逗號分隔的 story id（依 id 排序），下面是給 A 看的清單（日期、版別、狀態、來源數、標題）。
A 挑完的 15 個 id 交給 `scripts/run_exp2.py build --normal-ids`。只讀資料庫。
"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from reddit_tracker.daily.blind import EXP2_SEED, describe_exp2, sample_exp2  # noqa: E402
from reddit_tracker.db import session_scope  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dates", required=True)
    parser.add_argument("--seed", type=int, default=EXP2_SEED)
    args = parser.parse_args(argv)
    days = [date.fromisoformat(part) for part in args.dates.split(",") if part]
    with session_scope() as session:
        ids = sample_exp2(session, days, seed=args.seed)
        rows = describe_exp2(session, ids)
    print(",".join(str(item) for item in ids))
    print()
    print("| story id | 日期 | 版別 | 狀態 | 來源數 | 標題 |")
    print("| --- | --- | --- | --- | --- | --- |")
    for row in rows:
        headline = row["headline"].replace("|", "｜")
        print(f"| {row['story_id']} | {row['edition_date']} | {row['section']} | {row['status']} | {row['sources']} | {headline} |")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

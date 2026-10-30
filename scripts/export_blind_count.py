"""手動補匯出盲計稿與抽查表，一天一個目錄，內容和 06:00 自動匯出（`run.export_annotation`）一模一樣。

    uv run python scripts/export_blind_count.py --dates 2026-11-09,2026-11-10 --out annotation

每天寫到 OUT/YYYY-MM-DD/：blind.txt（P、M 都有寫的事件抽 8 篇、4 P／4 M、混合隨機編號）、spot-check.txt、
mapping.sha256，這個資料夾可以整個交給 B。對照表本體在當天資料夾之外的 OUT/_private/YYYY-MM-DD/mapping.json，
不要給標註員。共同事件 0 個的那天只有 README.txt 與 spot-check.txt。每天交給 B 之前把印出的雜湊 commit 進 repo
（方案 B；手冊原為 12/01 前）。抽樣規則見 `reddit_tracker/daily/blind.py::sample_day`。
輸出和 CLI `blind-export` 相同：`日期 雜湊 當天資料夾 對照表路徑`。
"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from reddit_tracker.daily.run import export_annotation_report  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dates", required=True, help="逗號分隔的 YYYY-MM-DD")
    parser.add_argument("--out", type=Path, required=True, help="annotation 根目錄")
    args = parser.parse_args(argv)
    for day in (date.fromisoformat(part) for part in args.dates.split(",") if part):
        print(export_annotation_report(day, args.out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

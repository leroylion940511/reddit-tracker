"""匯出盲計稿。對照表本體不寫進這個目錄，只寫 SHA-256。

    uv run python scripts/export_blind_count.py --dates 2026-12-01 --out annotation/2026-12-01

真人对照表請另存在不進 git 的地方。12/01 前把印出的雜湊 commit 進 repo。
"""

from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path

from reddit_tracker.daily.blind import export_blind_count, spot_check_sheet
from reddit_tracker.db import session_scope


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dates", required=True, help="逗號分隔的 YYYY-MM-DD")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    days = [date.fromisoformat(part) for part in args.dates.split(",") if part]
    args.out.mkdir(parents=True, exist_ok=True)
    with session_scope() as session:
        text, _mapping, digest = export_blind_count(session, days)
        spot = spot_check_sheet(session, days[0]) if days else ""
    (args.out / "blind.txt").write_text(text, encoding="utf-8")
    (args.out / "spot-check.txt").write_text(spot, encoding="utf-8")
    (args.out / "mapping.sha256").write_text(digest + "\n", encoding="utf-8")
    print(digest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

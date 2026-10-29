"""從 M 組稿用固定種子抽 25 篇，給標註員 A 挑 15 篇正常稿。

    uv run python scripts/sample_exp2.py --dates 2026-12-01,2026-12-02
"""

from __future__ import annotations

import argparse
from datetime import date

from reddit_tracker.daily.blind import EXP2_SEED, sample_exp2
from reddit_tracker.db import session_scope


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dates", required=True)
    parser.add_argument("--seed", type=int, default=EXP2_SEED)
    args = parser.parse_args(argv)
    days = [date.fromisoformat(part) for part in args.dates.split(",") if part]
    with session_scope() as session:
        ids = sample_exp2(session, days, seed=args.seed)
    print(",".join(str(item) for item in ids))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

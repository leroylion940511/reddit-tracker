"""用標註結果與對照表算 P／M 的四類錯誤。對照表在 B 交件之後才拿出來。

    uv run python scripts/analyze_blind_count.py --labels labels.json --mapping mapping.json

labels.json：{"1": {"class1": 0, "class2": 1, "class3": 0, "class4": 0}, ...}
mapping.json：export_blind_count 的對照表（編號 → variant／story_id）。
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from reddit_tracker.daily.blind import analyze_blind


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--labels", type=Path, required=True)
    parser.add_argument("--mapping", type=Path, required=True)
    args = parser.parse_args(argv)
    result = analyze_blind(json.loads(args.labels.read_text(encoding="utf-8")), json.loads(args.mapping.read_text(encoding="utf-8")))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

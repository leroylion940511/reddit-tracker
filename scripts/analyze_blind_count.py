"""用標註結果與對照表算 P／M 的錯誤數。對照表在 B 交件之後才拿出來。

    uv run python scripts/analyze_blind_count.py --labels labels.json --mapping annotation/2026-11-09/_private/mapping.json

labels.json：{"1": {"class1": 0, ..., "class7": 0, "guess": "P"}, ...}（guess 填 P／M／不知道）。
--mapping 可給多次（多天合併）；每個檔案先用 mapping.sha256 驗證（同目錄上一層有的話），不符就停。
輸出主指標（第 1–5 類 ÷ 篇數 × 10）、各類錯誤、HOLD 算已擋下的敏感度版本、B 猜組別的正確率。
多天時 labels 的鍵用「日期:編號」，例如 "2026-11-09:3"。
"""

from __future__ import annotations

import argparse
import sys
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from reddit_tracker.daily.blind import analyze_blind, mapping_digest  # noqa: E402


def _load(path: Path) -> dict:
    mapping = json.loads(path.read_text(encoding="utf-8"))
    committed = path.parent.parent / "mapping.sha256"
    if committed.exists():
        expected = committed.read_text().strip()
        if mapping_digest(mapping) != expected:
            raise SystemExit(f"{path} 的 SHA-256 跟 {committed} 不符，對照表可能被改過")
    return mapping


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--labels", type=Path, required=True)
    parser.add_argument("--mapping", type=Path, action="append", required=True)
    args = parser.parse_args(argv)
    labels = json.loads(args.labels.read_text(encoding="utf-8"))
    if len(args.mapping) == 1:
        mapping = _load(args.mapping[0])
    else:
        mapping = {}
        for path in args.mapping:
            for number, meta in _load(path).items():
                mapping[f"{meta['edition_date']}:{number}"] = meta
    print(json.dumps(analyze_blind(labels, mapping), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""實驗三結果（手冊 8.3）：B 的盲計 × 對照表 → docs/eval/exp3_results.md。

    # 第一次：把 B（agy）的原始輸出解析成 docs/eval/exp3/B_labels.json，再產報告
    uv run python scripts/exp3_results.py --start 2026-11-09 --end 2026-11-15 --from-raw annotation/exp3 --write
    # 之後重產（只讀已存檔的 B_labels.json）
    uv run python scripts/exp3_results.py --start 2026-11-09 --end 2026-11-15 --write

對照表一律經 `mapping.sha256` 驗證才讀（沿用 analyze_blind_count.py）；不碰 DB、不呼叫 LLM。
--write 會保留報告裡 MANUAL_MARKER 以下的手寫分析；不加 --write 只印到 stdout。
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from analyze_blind_count import _load  # noqa: E402

from reddit_tracker.eval.exp3 import compute, keep_manual, load_raw_labels, render_report  # noqa: E402


def _days(start: date, end: date) -> list[date]:
    return [start + timedelta(days=i) for i in range((end - start).days + 1)]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", type=date.fromisoformat, required=True)
    parser.add_argument("--end", type=date.fromisoformat, required=True)
    parser.add_argument("--root", type=Path, default=Path("annotation"), help="annotation 根目錄（讀 _private 對照表）")
    parser.add_argument("--labels", type=Path, default=Path("docs/eval/exp3/B_labels.json"))
    parser.add_argument("--from-raw", type=Path, help="B 原始輸出目錄（B_raw_YYYY-MM-DD.json）；給了就重建 --labels")
    parser.add_argument("--out", type=Path, default=Path("docs/eval/exp3_results.md"))
    parser.add_argument("--model-note", default="agy CLI（`agy -p`，預設模型，`--mode plan --sandbox`，每期只跑一次）")
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args(argv)
    days = _days(args.start, args.end)

    if args.from_raw:
        labels_by_day = {d.isoformat(): load_raw_labels(args.from_raw, args.root, d) for d in days}
        if args.write:
            args.labels.parent.mkdir(parents=True, exist_ok=True)
            args.labels.write_text(json.dumps(labels_by_day, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    else:
        labels_by_day = json.loads(args.labels.read_text(encoding="utf-8"))

    mappings = {d.isoformat(): _load(args.root, d) for d in days}
    result = compute(labels_by_day, mappings)
    stamp = datetime.now(ZoneInfo("Asia/Taipei")).strftime("%Y-%m-%d %H:%M 台北")
    report = render_report(result, stamp, args.model_note)
    if args.write:
        existing = args.out.read_text(encoding="utf-8") if args.out.is_file() else None
        args.out.write_text(keep_manual(report, existing), encoding="utf-8")
        print(f"寫入 {args.out}（{len(days)} 期）")
    else:
        print(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

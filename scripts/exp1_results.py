"""實驗一結果表（手冊步驟 9b、8.1）。只做算術：不碰 DB、不呼叫 LLM。

    uv run python scripts/exp1_results.py \\
        --a annotation/exp1/exp1_A_100.csv --b annotation/exp1/exp1_B_30.csv \\
        --final annotation/exp1/exp1_final.csv --annotators "A：王小明；B：李小華（本人標註）"

- `--a`／`--b`：標註員交回的 CSV（欄位同交出去的檔，`判斷` 填 是／不是／不確定）。
- `--final`：A、B 討論後的最終答案（欄位 `pair_id,final`）。兩人不一致的配對一定要有，否則停下來列出缺哪些。
- `--key`：抽樣時的私有對照表，預設 `annotation/exp1/_private/exp1_key.csv`。
- 預設只把報告印到 stdout。加 `--write` 才寫 `docs/eval/cluster_pairs_v1.csv` 與 `docs/eval/exp1_results.md`；
  `cluster_pairs_v1.csv` 寫了就不能改（手冊 8.1 第 5 點），已存在就停，不覆寫。
- 標註不能用 LLM 代做（手冊 8.1 第 4 點）；`--annotators` 必填，會寫進報告。
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from reddit_tracker.eval.exp1_results import (  # noqa: E402
    Exp1InputError, build_pairs, read_csv, render_report, write_pairs_csv,
)


def _frozen_commit() -> str:
    done = subprocess.run(["git", "rev-parse", "exp1-frozen^{commit}"], cwd=ROOT, capture_output=True, text=True)
    return done.stdout.strip() if done.returncode == 0 else "（找不到 tag exp1-frozen）"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--a", required=True)
    parser.add_argument("--b", required=True)
    parser.add_argument("--final")
    parser.add_argument("--key", default="annotation/exp1/_private/exp1_key.csv")
    parser.add_argument("--annotators", required=True)
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--out-dir", default=str(ROOT / "docs" / "eval"))
    args = parser.parse_args(argv)
    try:
        pairs = build_pairs(
            read_csv(args.key), read_csv(args.a), read_csv(args.b), read_csv(args.final) if args.final else None,
        )
    except Exp1InputError as exc:
        print(f"輸入有問題：{exc}", file=sys.stderr)
        return 2
    report = render_report(
        pairs, frozen_commit=_frozen_commit(), annotators=args.annotators,
        generated=datetime.now(ZoneInfo("Asia/Taipei")).strftime("%Y-%m-%d %H:%M 台北"),
    )
    if not args.write:
        print(report)
        return 0
    out_dir = Path(args.out_dir)
    pairs_path = out_dir / "cluster_pairs_v1.csv"
    if pairs_path.exists():
        print(f"{pairs_path} 已存在，標註存檔後不能再改；要重算報告請先確認並手動處理。", file=sys.stderr)
        return 2
    out_dir.mkdir(parents=True, exist_ok=True)
    write_pairs_csv(pairs, pairs_path)
    (out_dir / "exp1_results.md").write_text(report, encoding="utf-8")
    print(f"寫入 {pairs_path} 與 {out_dir / 'exp1_results.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

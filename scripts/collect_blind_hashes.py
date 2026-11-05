"""把試刊期間每天的盲計對照表雜湊整理成 docs/eval/blind_mapping.sha256。

    uv run python scripts/collect_blind_hashes.py --start 2026-11-09 --end 2026-11-09
    uv run python scripts/collect_blind_hashes.py --start 2026-11-09 --end 2026-11-15 --write

只讀 ROOT/YYYY-MM-DD/mapping.sha256（ROOT 由 --root 指定，預設 annotation），也就是 export_annotation 寫在
要交給 B 的資料夾裡的那一行雜湊；不讀 ROOT/_private/ 底下的對照表本體，也不重算雜湊（要驗證對照表請用
analyze_blind_count.py）。每天一行「YYYY-MM-DD  <sha256>」，預設只印到 stdout；加 --write 才附加到
--out（預設 docs/eval/blind_mapping.sha256）。檔案裡已有同一天同一雜湊就跳過；同一天雜湊不同就停，
表示當天重匯出過，要人工確認是哪一份交給了 B。當天沒有 mapping.sha256（README.txt 那種 0 篇的日子、
或兩組沒有都出稿）就跳過並在 stderr 註明。
"""

from __future__ import annotations

import argparse
import re
import sys
from datetime import date, timedelta
from pathlib import Path

_HASH = re.compile(r"[0-9a-f]{64}")


def collect(root: Path, start: date, end: date) -> tuple[list[tuple[date, str]], list[str]]:
    """回傳 (每天的雜湊, 跳過的原因)。只碰 ROOT/YYYY-MM-DD/mapping.sha256。"""
    if "_private" in root.parts:
        raise SystemExit(f"--root 不能指到 _private：{root}")
    if end < start:
        raise SystemExit(f"--end {end} 早於 --start {start}")
    found, skipped = [], []
    day = start
    while day <= end:
        path = root / day.isoformat() / "mapping.sha256"
        if not path.is_file():
            skipped.append(f"{day.isoformat()}：沒有 {path}")
        else:
            digest = path.read_text(encoding="utf-8").strip()
            if not _HASH.fullmatch(digest):
                raise SystemExit(f"{path} 不是 64 位小寫十六進位的 SHA-256：{digest!r}")
            found.append((day, digest))
        day += timedelta(days=1)
    return found, skipped


def _existing(out: Path) -> dict[str, str]:
    if not out.is_file():
        return {}
    rows = {}
    for number, line in enumerate(out.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        parts = line.split()
        if len(parts) != 2:
            raise SystemExit(f"{out} 第 {number} 行格式不對：{line!r}")
        rows[parts[0]] = parts[1]
    return rows


def append(out: Path, found: list[tuple[date, str]]) -> list[str]:
    """把還沒記過的日期附加到 out，回傳新寫入的行。"""
    existing = _existing(out)
    lines = []
    for day, digest in found:
        key = day.isoformat()
        if key in existing:
            if existing[key] != digest:
                raise SystemExit(f"{out} 已記 {key} 的雜湊 {existing[key]}，跟現在的 {digest} 不同；請人工確認交給 B 的是哪一份")
            continue
        lines.append(f"{key}  {digest}")
    if lines:
        out.parent.mkdir(parents=True, exist_ok=True)
        with out.open("a", encoding="utf-8") as handle:
            handle.write("".join(line + "\n" for line in lines))
    return lines


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", type=date.fromisoformat, required=True, help="YYYY-MM-DD（含）")
    parser.add_argument("--end", type=date.fromisoformat, required=True, help="YYYY-MM-DD（含）")
    parser.add_argument("--root", type=Path, default=Path("annotation"), help="annotation 根目錄")
    parser.add_argument("--out", type=Path, default=Path("docs/eval/blind_mapping.sha256"))
    parser.add_argument("--write", action="store_true", help="附加到 --out；沒給就只印出來")
    args = parser.parse_args(argv)
    found, skipped = collect(args.root, args.start, args.end)
    for reason in skipped:
        print(f"跳過 {reason}", file=sys.stderr)
    if not args.write:
        for day, digest in found:
            print(f"{day.isoformat()}  {digest}")
        return 0
    lines = append(args.out, found)
    for line in lines:
        print(line)
    print(f"寫入 {len(lines)} 行到 {args.out}（已有的 {len(found) - len(lines)} 天跳過）", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

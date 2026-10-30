"""用標註結果與對照表算 P／M 的錯誤數。對照表在 B 交件之後才拿出來。

    uv run python scripts/analyze_blind_count.py --labels labels.json --date 2026-11-09
    uv run python scripts/analyze_blind_count.py --labels labels.json --mapping annotation/_private/2026-11-09/mapping.json

labels.json：{"1": {"class1": 0, ..., "class7": 0, "guess": "P"}, ...}（guess 填 P／M／不知道）。
--date 讀 ROOT/_private/YYYY-MM-DD/mapping.json（ROOT 由 --root 指定，預設 annotation）；--mapping 直接給
這個位置的檔案（相容舊用法）。兩者都可給多次（多天合併）。每個對照表都用 ROOT/YYYY-MM-DD/mapping.sha256 驗證，
雜湊檔不在或不符就停。對照表若還在舊位置 ROOT/YYYY-MM-DD/_private/mapping.json（2026-10-30 前）也會停：
那個資料夾是要整個交給 B 的，請先把對照表移到新位置。
輸出主指標（第 1–5 類 ÷ 篇數 × 10）、各類錯誤、HOLD 算已擋下的敏感度版本、B 猜組別的正確率。
多天時 labels 的鍵用「日期:編號」，例如 "2026-11-09:3"。
"""

from __future__ import annotations

import argparse
import sys
import json
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from reddit_tracker.daily.blind import (  # noqa: E402
    analyze_blind,
    legacy_mapping_path,
    mapping_digest,
    private_mapping_path,
)


def _check_legacy(root: Path, day: date) -> None:
    legacy = legacy_mapping_path(root, day)
    if legacy.exists():
        raise SystemExit(
            f"對照表在舊位置 {legacy}：2026-10-30 起改放 {private_mapping_path(root, day)}。"
            f"請把它移到新位置並刪掉 {legacy.parent}；{root / day.isoformat()} 是要整個交給 B 的資料夾，"
            "對照表留在裡面會破壞盲化（若已交出含 _private/ 的資料夾，請記錄這件事）。"
        )


def _load(root: Path, day: date) -> dict:
    _check_legacy(root, day)
    path = private_mapping_path(root, day)
    if not path.is_file():
        raise SystemExit(f"找不到對照表 {path}（應由 export_annotation 寫在 {root / '_private' / day.isoformat()}/）")
    committed = root / day.isoformat() / "mapping.sha256"
    if not committed.is_file():
        raise SystemExit(f"找不到 {committed}，無法驗證 {path}")
    mapping = json.loads(path.read_text(encoding="utf-8"))
    if mapping_digest(mapping) != committed.read_text().strip():
        raise SystemExit(f"{path} 的 SHA-256 跟 {committed} 不符，對照表可能被改過")
    return mapping


def _as_date(name: str) -> date | None:
    try:
        return date.fromisoformat(name)
    except ValueError:
        return None


def _from_mapping_arg(path: Path) -> tuple[Path, date]:
    """--mapping ROOT/_private/YYYY-MM-DD/mapping.json → (ROOT, 日期)；舊位置或其他形狀都停。"""
    path = path.resolve()
    day = _as_date(path.parent.name)
    if day is not None and path.parent.parent.name == "_private":
        return path.parents[2], day
    legacy_day = _as_date(path.parent.parent.name)
    if legacy_day is not None and path.parent.name == "_private":
        _check_legacy(path.parents[2], legacy_day)
    raise SystemExit(f"--mapping 要給 ROOT/_private/YYYY-MM-DD/mapping.json，收到 {path}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--labels", type=Path, required=True)
    parser.add_argument("--date", type=date.fromisoformat, action="append", default=[], help="YYYY-MM-DD，可給多次")
    parser.add_argument("--root", type=Path, default=Path("annotation"), help="annotation 根目錄（搭配 --date）")
    parser.add_argument(
        "--mapping", type=Path, action="append", default=[],
        help="ROOT/_private/YYYY-MM-DD/mapping.json，可給多次（相容舊用法；建議改用 --date）",
    )
    args = parser.parse_args(argv)
    targets = [(args.root, day) for day in args.date] + [_from_mapping_arg(path) for path in args.mapping]
    if not targets:
        parser.error("至少給一個 --date 或 --mapping")
    labels = json.loads(args.labels.read_text(encoding="utf-8"))
    if len(targets) == 1:
        mapping = _load(*targets[0])
    else:
        mapping = {}
        for root, day in targets:
            for number, meta in _load(root, day).items():
                mapping[f"{meta['edition_date']}:{number}"] = meta
    print(json.dumps(analyze_blind(labels, mapping), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

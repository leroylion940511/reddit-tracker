"""實驗一配對抽樣（手冊步驟 5、第 8.1 節）。不呼叫 LLM；來源 DB 只用唯讀 URI 開。

    # 11/03 正式抽樣：先由開發者從 production 做新的唯讀快照（不在本工具範圍），再：
    uv run python scripts/sample_exp1.py --db data/snapshots/2026-11-03.db

    # 試跑（母本只到 10/29，test 期還沒發生）
    uv run python scripts/sample_exp1.py --db data/snapshots/2026-10-27.db --out annotation/exp1-trial

輸出（`annotation/` 已 gitignore，不進 repo）：
- `<out>/exp1_A_100.csv`、`.xlsx`：A 標全部（dev、test 兩個工作表）
- `<out>/exp1_B_30.csv`、`.xlsx`：B 複標 30 組
- `<out>/_private/exp1_key.csv`、`manifest.json`：分層、方法判斷、相似度、素材 id（**不給標註員**）
種子：`reddit_tracker/eval/exp1.py` 的 `SEED`（可用 `--seed` 覆寫，但正式抽樣用預設）。
"""

from __future__ import annotations

import argparse
import csv
import json
import random
import subprocess
import sys
from collections import Counter
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from reddit_tracker.collection.collector import recompute_duplicates  # noqa: E402
from reddit_tracker.collection.entities import MergeRules, load_lexicon  # noqa: E402
from reddit_tracker.config import get_settings  # noqa: E402
from reddit_tracker.eval import exp1  # noqa: E402
from reddit_tracker.seeds.news_sources import load_registry  # noqa: E402

DEFAULT_DB = ROOT / "data/snapshots/2026-10-27.db"
DEFAULT_OUT = ROOT / "annotation/exp1"
CASES_DIR = ROOT / "tests/regression/cases"


def _dates(text: str) -> tuple[date, date]:
    first, _, last = text.partition("..")
    return date.fromisoformat(first), date.fromisoformat(last or first)


def _commit() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    except OSError:
        return "unknown"


def run(db: Path, out: Path, *, dev, test, seed: int, round_hours: float, log=print) -> exp1.SampleResult:
    settings = get_settings()
    registry = load_registry(settings.news_sources_path)
    disabled = registry.disabled_source_ids()
    lexicon = load_lexicon()
    all_dates = exp1.date_range(dev[0], dev[1]) + exp1.date_range(test[0], test[1])
    end = exp1.edition_cutoff(test[1])
    items = exp1.load_items(db, until=end)
    if not items:
        raise SystemExit("來源 DB 沒有素材")
    latest = max(i.first_seen_at for i in items)
    end = min(end, latest)
    log(f"[exp1] {len(items)} items until {exp1.taipei_time(end)} (台北)")

    # 方法 A：舊規則同語言聚合＋各期 find_same_events 重播
    cluster_a, _ = exp1.simulate(
        items, rules=exp1.METHOD_A_RULES, lexicon=lexicon, registry=registry, recompute=False,
        disabled_sources=frozenset(), end=end, round_hours=round_hours,
    )
    merged = exp1.load_merged_groups(db, all_dates)
    live: dict[int, list[int]] = {}
    for item in items:
        if item.cluster_id is not None:
            live.setdefault(item.cluster_id, []).append(item.id)
    groups_a = []
    replay = {}
    for day, groups in merged.items():
        if groups is None:
            replay[day.isoformat()] = "沒有紀錄（那期不存在或 stats 沒有 merged_groups）"
            continue
        mapped = exp1.replay_groups(groups, live, cluster_a)
        groups_a += mapped
        replay[day.isoformat()] = f"重播 {len(groups)} 組 → {len(mapped)} 組"
    log(f"[exp1] method A: {len(set(v for v in cluster_a.values() if v))} clusters, replay {replay}")

    # 方法 C：步驟 3 現行版（兩段門檻＋共同實體＋譯名表）＋每期 06:00 desk 跨語言規則
    cluster_c, groups_c = exp1.simulate(
        items, rules=MergeRules.from_settings(settings), lexicon=lexicon, registry=registry, recompute=True,
        disabled_sources=disabled, end=end, round_hours=round_hours, edition_dates=all_dates, desk=True,
    )
    log(f"[exp1] method C: {len(set(v for v in cluster_c.values() if v))} clusters, desk groups {len(groups_c)}")

    comp_a = exp1.Components(cluster_a, groups_a)
    comp_c = exp1.Components(cluster_c, groups_c)
    rows = [exp1._row(i) for i in items]
    recompute_duplicates(rows)
    c_duplicates = {r.id: r.duplicate_of_id for r in rows}
    eligible = exp1.eligible_items(items, disabled, c_duplicates, dev, test)
    log(f"[exp1] eligible items: {dict(Counter(eligible.values()))}")
    pairs = exp1.build_pairs(items, eligible, comp_a, comp_c)
    log(f"[exp1] candidate pairs: {len(pairs)}")

    forced, error_items = exp1.error_case_pairs(items, exp1.error_case_title_pairs(CASES_DIR))
    rng = random.Random(seed)
    by_id = {i.id: i for i in items}

    def filler(split, exclude, count):
        return exp1.fill_pairs(items, eligible, comp_a, comp_c, split, exclude, rng, count)

    result = exp1.sample(pairs, rng=rng, forced=forced, error_items=error_items, filler=filler)
    result.merge_replay = replay

    a_rows = exp1.annotation_rows(result.selected, by_id, result.pair_ids, rng)
    b_rows = exp1.annotation_rows(result.b_pairs, by_id, result.pair_ids, rng)
    exp1.write_csv(out / "exp1_A_100.csv", a_rows)
    exp1.write_csv(out / "exp1_B_30.csv", b_rows)
    exp1.write_xlsx(out / "exp1_A_100.xlsx", {
        "dev": [r for r in a_rows if r[0].startswith("D")], "test": [r for r in a_rows if r[0].startswith("T")],
    }, exp1.INSTRUCTIONS)
    exp1.write_xlsx(out / "exp1_B_30.xlsx", {"B複標": b_rows}, exp1.INSTRUCTIONS)

    private = out / "_private"
    private.mkdir(parents=True, exist_ok=True)
    b_keys = {p.key for p in result.b_pairs}
    with (private / "exp1_key.csv").open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["pair_id", "split", "kind", "stratum", "filled", "a_merged", "c_merged", "similarity",
                         "error_case", "b_double", "item_1", "item_2", "lang_1", "lang_2", "section_1", "section_2"])
        for p in sorted(result.selected, key=lambda p: result.pair_ids[p.key]):
            a, b = by_id[p.a], by_id[p.b]
            writer.writerow([result.pair_ids[p.key], p.split, p.kind, p.stratum, p.filled, p.a_merged, p.c_merged,
                             p.similarity, p.error_case or "", p.key in b_keys, p.a, p.b, a.lang, b.lang,
                             a.section, b.section])
    counts = Counter((p.split, p.kind, p.stratum, p.filled) for p in result.selected)
    manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "commit": _commit(),
        "seed": seed,
        "db": str(db),
        "db_sha256": exp1.sha256_of(db),
        "dev_dates": [d.isoformat() for d in dev],
        "test_dates": [d.isoformat() for d in test],
        "items_until_utc": end.isoformat(),
        "round_hours": round_hours,
        "method_a": "TF-IDF 0.28 同語言聚合（METHOD_A_RULES）＋各期 merged_groups 重播",
        "method_c": "MergeRules.from_settings＋共同實體＋譯名表＋desk 跨語言（無 LLM 第二意見）",
        "merge_replay": replay,
        "eligible_items": dict(Counter(eligible.values())),
        "candidate_pools": result.pools,
        "selected": {f"{s}/{k}/{st}{'/filled' if f else ''}": n for (s, k, st, f), n in sorted(counts.items(), key=str)},
        "selected_total": {s: sum(1 for p in result.selected if p.split == s) for s in ("dev", "test")},
        "b_double": {s: sum(1 for p in result.b_pairs if p.split == s) for s in ("dev", "test")},
        "shortages": result.shortages,
        "error_cases": {p.error_case: result.pair_ids[p.key] for p in result.selected if p.error_case},
        "error_cases_available": {k: len(v) for k, v in forced.items()},
    }
    (private / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    log(f"[exp1] selected {manifest['selected_total']} B {manifest['b_double']} shortages {len(result.shortages)}")
    log(f"[exp1] wrote {out}")
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB, help="來源 DB（唯讀開啟）")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--dev", type=_dates, default=exp1.DEV_DATES, help="出刊日範圍 YYYY-MM-DD..YYYY-MM-DD")
    parser.add_argument("--test", type=_dates, default=exp1.TEST_DATES)
    parser.add_argument("--seed", type=int, default=exp1.SEED)
    parser.add_argument("--round-hours", type=float, default=3.0, help="模擬增量聚合的間隔（線上是 15 分鐘）")
    args = parser.parse_args(argv)
    if not args.db.exists():
        raise SystemExit(f"找不到 {args.db}")
    run(args.db, args.out, dev=args.dev, test=args.test, seed=args.seed, round_hours=args.round_hours)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

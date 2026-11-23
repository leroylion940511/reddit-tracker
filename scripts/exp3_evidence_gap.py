"""實驗三：P、M 兩組實際用的證據包差多少、差在哪裡（只讀資料庫，印 Markdown）。

    uv run python scripts/exp3_evidence_gap.py --db /path/to/copy.db --start 2026-11-09 --end 2026-11-15

兩組讀同一份 `daily_snapshots`，但建證據包的路徑不同：P 是 `build_evidence`（帶當天 `EntityContext`、不限網域），
M 是 `build_evidence_from_ids`（不帶 context、`allowed_domains`＝登錄表 feed 網址的網域）。這裡用同一份快照重建
四種組合，和資料庫裡兩組 v1 的 `source_ids` 比對，確認差異來自這兩個參數。
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "scripts")]

from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from reddit_tracker.collection.clustering import domain_of, outlet_of  # noqa: E402
from reddit_tracker.collection.entities import load_lexicon  # noqa: E402
from reddit_tracker.config import get_settings  # noqa: E402
from reddit_tracker.daily.evidence import build_evidence_from_ids, title_context  # noqa: E402
from reddit_tracker.daily.mas.orchestrator import registry_domains  # noqa: E402
from reddit_tracker.models import SourceItem  # noqa: E402
from reddit_tracker.seeds.news_sources import load_registry  # noqa: E402
from trial_metrics import VARIANTS, open_ro  # noqa: E402


COMBOS = ("ctx", "none", "ctx+dom", "dom")


def rebuild(session, raw: dict, names, context, domains) -> dict[str, list[int]]:
    """同一份快照候選，四種參數組合各建一次證據包（素材 id）。`ctx`＝P 的參數，`dom`＝M 的參數。"""
    packs = {}
    for combo in COMBOS:
        pack = build_evidence_from_ids(
            session, list(raw.get("evidence_item_ids") or []), names, anchor_item_id=raw.get("anchor_item_id"),
            context=context if "ctx" in combo else None, allowed_domains=domains if "dom" in combo else None,
        )
        packs[combo] = [item.item_id for item in pack.items]
    return packs


def collect(conn, session, registry, days: list[date]) -> dict:
    names = {source.id: source.name for source in registry.sources}
    domains = registry_domains(registry)
    total, dropped = Counter(), Counter()
    for day in days:
        row = conn.execute("SELECT created_at, candidates FROM daily_snapshots WHERE edition_date=?", (day.isoformat(),)).fetchone()
        if row is None:
            continue
        now = datetime.fromisoformat(row[0]).replace(tzinfo=timezone.utc)
        raw_of = {raw["keeper_cluster_id"]: raw for raw in json.loads(row[1])}
        context = title_context(session, now, load_lexicon(), registry.disabled_source_ids())
        used = {v: {} for v in VARIANTS}
        sections = {}
        for variant, keeper, section, sources in conn.execute(
            "SELECT s.run_variant, s.keeper_cluster_id, s.section, v.source_ids FROM stories s "
            "JOIN story_versions v ON v.story_id=s.id AND v.version=1 WHERE s.edition_date=?", (day.isoformat(),)):
            used[variant][keeper] = json.loads(sources or "[]")
            sections[keeper] = section
        for keeper in sorted(set(used["pipeline"]) & set(used["mas"])):
            p, m = used["pipeline"][keeper], used["mas"][keeper]
            packs = rebuild(session, raw_of[keeper], names, context, domains)
            section = sections[keeper]
            total["pairs"] += 1
            total["same"] += set(p) == set(m)
            total["P=ctx"] += set(p) == set(packs["ctx"])
            total["M=dom"] += set(m) == set(packs["dom"])
            for label, ids in (("P", p), ("M", m)):
                total[label] += len(ids)
                total[f"{label}/{section}"] += len(ids)
                total[f"{label} single"] += len(ids) == 1
            for combo, ids in packs.items():
                total[combo] += len(ids)
            for item in session.query(SourceItem).filter(SourceItem.id.in_(packs["ctx"])):
                domain = domain_of(item.canonical_url)
                if domain not in domains and outlet_of(item.canonical_url, item.title, item.summary) not in domains:
                    dropped[domain] += 1
    return {"total": total, "dropped": dropped}


def render(result: dict) -> str:
    t = result["total"]
    lines = [
        f"配對事件 {t['pairs']} 對；兩組 v1 證據來源完全相同的 {t['same']} 對。",
        "",
        "| 版 | P 來源數 | M 來源數 |",
        "| --- | --- | --- |",
        *(f"| {s} | {t[f'P/{s}']} | {t[f'M/{s}']} |" for s in ("taiwan", "world", "tech")),
        f"| 合計 | {t['P']} | {t['M']} |",
        f"| 只有 1 個來源的稿 | {t['P single']} | {t['M single']} |",
        "",
        "同一份快照重建（總來源數）：",
        "",
        "| 當天 EntityContext | 網域白名單 | 總來源數 | 和資料庫 v1 一致 |",
        "| --- | --- | --- | --- |",
        f"| 有 | 無 | {t['ctx']} | P {t['P=ctx']}／{t['pairs']} |",
        f"| 無 | 無 | {t['none']} | — |",
        f"| 有 | 有 | {t['ctx+dom']} | — |",
        f"| 無 | 有 | {t['dom']} | M {t['M=dom']}／{t['pairs']} |",
        "",
        "「有 context、無白名單」的證據裡，會被網域白名單剔除的素材："
        + "、".join(f"{domain} {n}" for domain, n in result["dropped"].most_common()) + "。",
    ]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--db", required=True)
    parser.add_argument("--start", type=date.fromisoformat, required=True)
    parser.add_argument("--end", type=date.fromisoformat, required=True)
    args = parser.parse_args()
    conn = open_ro(args.db)
    engine = create_engine("sqlite://", creator=lambda: open_ro(args.db))
    registry = load_registry(get_settings().news_sources_path)
    days = [args.start + timedelta(days=n) for n in range((args.end - args.start).days + 1)]
    with Session(engine) as session:
        print(render(collect(conn, session, registry, days)))


if __name__ == "__main__":
    main()

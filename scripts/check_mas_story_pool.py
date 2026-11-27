"""P3-1 離線等價檢查：`mas_story_keepers`（只為候選池建 Story）vs 舊做法（每個候選都建一列再挑）。

用法（DB 一律指向 Lab 複本；以 immutable 唯讀開啟，不寫入、不呼叫模型）：

    REDDIT_TRACKER_NO_DOTENV=1 uv run python scripts/check_mas_story_pool.py \\
      --db /Users/leroy/Documents/Developer/Lab/rt-data-1123/reddit_tracker.db

每期 `daily_snapshots` 印一行：候選數、新做法要建的列數、舊做法分版主編看得到的稿數、是否相同、
實際寫過稿的 M 組 story（有 story_versions）是否都在新集合裡。證據包用 `MAS_FULL_EVIDENCE` 關閉時的參數
（線上預設）。有任何一期不同就以 exit code 1 結束。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import create_engine, select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from reddit_tracker.daily.evidence import build_evidence_from_ids  # noqa: E402
from reddit_tracker.daily.mas import orchestrator as o  # noqa: E402
from reddit_tracker.models import DailySnapshot, Story, StoryVersion  # noqa: E402
from reddit_tracker.seeds.news_sources import load_registry  # noqa: E402


def check_day(session: Session, snapshot: DailySnapshot, names: dict, domains) -> tuple[bool, str]:
    candidates = list(snapshot.candidates)
    packs: dict[int, list] = {}

    def items(raw):
        keeper = raw["keeper_cluster_id"]
        if keeper not in packs:
            packs[keeper] = build_evidence_from_ids(
                session, list(raw.get("evidence_item_ids") or []), names,
                anchor_item_id=raw.get("anchor_item_id"), allowed_domains=domains,
            ).items
        return packs[keeper]

    new = set(o.mas_story_keepers(candidates, {}, items))
    stories = [SimpleNamespace(id=i, keeper=r["keeper_cluster_id"], section=r["section"], kind=r["kind"],
                               score=r.get("score") or 0) for i, r in enumerate(candidates)]
    evidence = {s.id: items(candidates[s.id]) for s in stories}
    old = set()
    for section in o.SECTIONS:
        old |= {s.keeper for s in o.section_pool(stories, evidence, section)}
    top = sorted((s for s in stories if s.section in o.SECTIONS), key=lambda s: -s.score)[:o.GLOBAL_TOP_N]
    old |= {s.keeper for s in top}
    default = {stories[p.story_id].keeper for p in o._default_pitches(stories, evidence)}
    written = set(session.scalars(select(Story.keeper_cluster_id).where(
        Story.edition_date == snapshot.edition_date, Story.run_variant == "mas",
        Story.id.in_(select(StoryVersion.story_id)))))
    ok = old == new and default <= new and written <= new
    line = (f"{snapshot.edition_date} candidates={len(candidates)} new={len(new)} old={len(old)} "
            f"{'EQUAL' if old == new else 'DIFF'} default⊂new={default <= new} "
            f"written⊂new={written <= new} (written={len(written)})")
    if old != new:
        line += f"\n  only_old={sorted(old - new)} only_new={sorted(new - old)}"
    return ok, line


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--db", required=True, help="SQLite 複本路徑（唯讀開啟）")
    args = parser.parse_args(argv)
    engine = create_engine(f"sqlite:///file:{Path(args.db).resolve()}?immutable=1&uri=true")
    registry = load_registry()
    names = {s.id: s.name for s in registry.sources}
    domains = o.registry_domains(registry)
    all_ok = True
    with Session(engine) as session:
        for snapshot in session.scalars(select(DailySnapshot).order_by(DailySnapshot.edition_date)):
            ok, line = check_day(session, snapshot, names, domains)
            all_ok &= ok
            print(line)
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

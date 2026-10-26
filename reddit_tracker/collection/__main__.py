"""收集層 CLI。

    uv run python -m reddit_tracker.collection run [--only id1,id2] [--force]
    uv run python -m reddit_tracker.collection report [--days 7] [--out report.md]
    uv run python -m reddit_tracker.collection cluster
    uv run python -m reddit_tracker.collection clusters [--top 30] [--hours 48]
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from ..config import get_settings
from ..db import session_scope
from ..models import SourceItem, StoryCluster
from ..seeds.news_sources import load_registry
from .clustering import cluster_recent_items
from .collector import collect_due_sources
from .report import build_collection_report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m reddit_tracker.collection")
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="抓取到期來源")
    run.add_argument("--only", help="逗號分隔的來源 id")
    run.add_argument("--force", action="store_true", help="忽略 interval_min，全部抓一次")
    report = sub.add_parser("report", help="輸出收集驗收報表")
    report.add_argument("--days", type=int, default=7)
    report.add_argument("--out", help="寫入 Markdown 檔")
    sub.add_parser("cluster", help="聚合時間窗內尚未分配事件的素材")
    clusters = sub.add_parser("clusters", help="列出出處最多的事件，供抽查")
    clusters.add_argument("--top", type=int, default=30)
    clusters.add_argument("--hours", type=int, default=48)
    args = parser.parse_args(argv)

    settings = get_settings()
    logging.basicConfig(level=settings.log_level, format="%(asctime)s %(levelname)s %(name)s | %(message)s")
    registry = load_registry(settings.news_sources_path)

    with session_scope() as session:
        if args.command == "run":
            only = set(args.only.split(",")) if args.only else None
            stats = collect_due_sources(session, registry, only=only, force=args.force)
            for stat in stats:
                mark = "OK  " if stat.ok else "FAIL"
                print(f"{mark} {stat.source_id:<28} returned={stat.returned} new={stat.new} dup={stat.duplicate}"
                      + (f" {stat.error}" if stat.error else ""))
            print(f"\n{sum(s.ok for s in stats)}/{len(stats)} 個來源成功，新增 {sum(s.new for s in stats)} 筆"
                  f"（其中重複 {sum(s.duplicate for s in stats)} 筆）")
        elif args.command == "cluster":
            print(cluster_recent_items(session, general_sources=registry.general_source_ids()))
        elif args.command == "clusters":
            _print_clusters(session, top=args.top, hours=args.hours)
        else:
            text = build_collection_report(session, registry, days=args.days)
            if args.out:
                with open(args.out, "w", encoding="utf-8") as fh:
                    fh.write(text)
            print(text)
    return 0


def _print_clusters(session, *, top: int, hours: int) -> None:
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    rows = session.scalars(
        select(StoryCluster)
        .where(StoryCluster.last_published_at >= since)
        .order_by(StoryCluster.outlet_count.desc(), StoryCluster.item_count.desc())
        .limit(top)
    ).all()
    for cluster in rows:
        print(f"\n#{cluster.id} [{cluster.section}] 出處={cluster.outlet_count} 素材={cluster.item_count} "
              f"T1={cluster.t1_count} T2={cluster.t2_count} T4={cluster.t4_count} | {cluster.title}")
        for item in session.scalars(
            select(SourceItem).where(SourceItem.cluster_id == cluster.id).order_by(SourceItem.published_at)
        ):
            print(f"    {item.source_id:<24} {(item.title or '')[:70]}")


if __name__ == "__main__":
    sys.exit(main())

"""手冊步驟 4 驗證：在 `data/work/1027_step4.db`（步驟 3.8 重編複本的複本）用 template writer 重編 10/27。

    uv run python scripts/validate_step4_1027.py

不呼叫任何 LLM（template writer、不跑編輯會議的 LLM 第二意見）；數據欄沿用母本 10/27 當期數值。
印出各版篇數、頭版 6 則、短訊、兩岸／財經事件的去向（含沒入選的兩岸事件在新版裡排第幾）。
"""

from __future__ import annotations

import json
import os
import shutil
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "scripts")]

import rebuild_1027 as rb  # noqa: E402

STEP4_DB = rb.WORK / "1027_step4.db"


def main() -> int:
    if not rb.REBUILD_DB.exists():
        raise SystemExit("先跑 scripts/rebuild_1027.py 產生 data/work/1027_rebuild.db")
    for suffix in ("", "-wal", "-shm"):
        Path(f"{STEP4_DB}{suffix}").unlink(missing_ok=True)
    shutil.copyfile(rb.REBUILD_DB, STEP4_DB)
    os.environ["DATABASE_URL"] = f"sqlite:///{STEP4_DB}"
    os.environ["LLM_QUOTA_STATE_PATH"] = str(rb.QUOTA_STATE)
    os.environ["DAILY_SITE_DIR"] = str(rb.WORK / "site-step4")
    from reddit_tracker.config import get_settings

    get_settings.cache_clear()
    assert get_settings().database_url == f"sqlite:///{STEP4_DB}"
    from reddit_tracker.daily import run
    from reddit_tracker.db import session_scope
    from reddit_tracker.models import DailyEdition

    captured = {}
    plan_edition = run.plan_edition

    def capture(session, **kwargs):
        captured["plan"] = plan_edition(session, **kwargs)
        return captured["plan"]

    market = rb.old_market()
    run.fetch_market_box = lambda: market
    run.plan_edition = capture
    edition_id = run.prepare_daily(rb.EDITION_DATE, now=rb.NOW, writer_mode="template", refresh=True)
    plan = captured["plan"]

    with session_scope() as session:
        edition = session.get(DailyEdition, edition_id)
        articles = sorted(edition.articles, key=lambda a: (not a.is_front, a.section, a.position))
        stats = edition.stats
        print(f"edition={edition.id} writer={edition.writer} html={edition.html_path}")
        print(f"正式稿 {len(articles)} 篇：{dict(Counter(a.section for a in articles))}；頭版 {sum(a.is_front for a in articles)} 則")
        print(f"LLM 請求 {stats['llm_requests']}；短訊 {len(stats['briefs'])} 則；改寫分版 {json.dumps(stats['section_rewrites'], ensure_ascii=False)}")
        print("\n[頭版]")
        for a in (a for a in articles if a.is_front):
            print(f"  {a.position}. ({a.section}/{a.kind}) {a.headline[:60]}  ← {(a.signals or {}).get('original_section') or '—'}")
        print("\n[內版]")
        for a in sorted(articles, key=lambda a: (a.section, (a.signals or {}).get('section_position') or a.position)):
            mark = "→頭版連結" if a.is_front else ""
            print(f"  {a.section} #{(a.signals or {}).get('section_position')} {a.headline[:60]} {mark}"
                  f"  ← {(a.signals or {}).get('original_section') or '—'}")
        print("\n[短訊]")
        for b in stats["briefs"]:
            print(f"  {b['section']}: {b['headline'][:60]}（{b['outlet']}）")

    print("\n[兩岸／財經事件去向（各取分數前 5）]")
    for origin in ("cross_strait", "finance"):
        moved = [s for s in plan.candidates if s.signals.get("original_section") == origin]
        chosen = {p.selection.cluster.cluster_id for p in plan.planned}
        for s in sorted(moved, key=lambda s: -s.score)[:5]:
            rank = 1 + sum(
                1 for o in plan.candidates
                if o.section == s.section and o.kind in ("report", "single_source")
                and (o.kind, -o.score) < (s.kind, -s.score) and o.cluster_id != s.cluster_id
            ) if s.kind in ("report", "single_source") else None
            print(f"  {origin}→{s.section} {s.kind} {s.score:.1f} 版內第 {rank} 名 {'✅刊出' if s.cluster_id in chosen else ''}"
                  f"｜{s.signals.get('section_rule')}｜cluster {s.cluster_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

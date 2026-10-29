"""手冊步驟 3 第 8 點：在 `data/work/1027_rebuild.db` 複本上用修好的程式一次重聚＋重編 10/27。

    uv run python scripts/rebuild_1027.py                 # 撰稿用真 Codex（錄進複本 llm_records）
    uv run python scripts/rebuild_1027.py --writer template

步驟（全部在複本上；母本只用 `mode=ro&immutable=1` 讀）：
1. `cp` 母本 → 複本（舊複本裡錄過的 llm_records 會搬到新複本，重跑不重新呼叫 Codex）。
2. 刪 `first_seen_at` 晚於 10/27 06:00 台北（DB 是 UTC naive＝10/26 22:00）的素材。
3. 清 `source_items.cluster_id`／`duplicate_of_id` 與 `story_clusters`；刪**所有**
   `daily_articles`、`daily_editions`（重編時不排除前幾期已刊事件）。
4. `collector.recompute_duplicates` 用現在的指紋規則重算重複稿。
5. `run.recluster(now)` 一次重聚 → `run.prepare_daily(now=now)`，`now`＝10/27 06:00 台北。
   數據欄用母本 10/27 當期記錄的數值（不連網抓今天的證交所）。

真 Codex 規則：`LLM_QUOTA_STATE_PATH=data/work/llm-quota-1027.json`；整個任務嘗試上限
`--max-attempts`（預設 60，帳本是 `data/work/` 下所有錄音複本）；同 request_hash 已有 ok 就重用。
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import shutil
import sqlite3
import sys
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "scripts")]
SNAPSHOT = ROOT / "data/snapshots/2026-10-27.db"
WORK = ROOT / "data/work"
REBUILD_DB = WORK / "1027_rebuild.db"
QUOTA_STATE = WORK / "llm-quota-1027.json"
# 本任務所有真 Codex 錄音的帳本（一起算上限、一起查重用）
LEDGERS = [REBUILD_DB, WORK / "1027_regression_record" / "1027_rebuild.db"]
EDITION_DATE = date(2026, 10, 27)
NOW = datetime(2026, 10, 26, 22, 0, tzinfo=timezone.utc)  # 10/27 06:00 台北
CUTOFF_SQL = "2026-10-26 22:00:00"  # source_items.first_seen_at 是 UTC naive 字串


def snapshot_uri() -> str:
    return f"file:{SNAPSHOT}?mode=ro&immutable=1"


def configure_env() -> None:
    """一定要在讀 settings 之前：DB、額度 state 檔、HTML 輸出都指到 data/work。"""
    os.environ["DATABASE_URL"] = f"sqlite:///{REBUILD_DB}"
    os.environ["LLM_QUOTA_STATE_PATH"] = str(QUOTA_STATE)
    os.environ["DAILY_SITE_DIR"] = str(WORK / "site")
    from reddit_tracker.config import get_settings

    get_settings.cache_clear()
    settings = get_settings()
    assert settings.database_url == f"sqlite:///{REBUILD_DB}"
    assert Path(settings.llm_quota_state_path) == QUOTA_STATE


def old_market() -> list[dict] | None:
    conn = sqlite3.connect(snapshot_uri(), uri=True)
    try:
        row = conn.execute("SELECT stats FROM daily_editions WHERE edition_date = ?", (EDITION_DATE.isoformat(),)).fetchone()
    finally:
        conn.close()
    return (json.loads(row[0]) or {}).get("market") if row else None


def fresh_copy() -> int:
    """複製母本；舊複本裡本任務錄的 llm_records 搬過來。回傳搬過來的筆數。"""
    from llm_recorder import restore_records, saved_records

    saved = saved_records(REBUILD_DB)
    WORK.mkdir(parents=True, exist_ok=True)
    for suffix in ("", "-wal", "-shm"):
        Path(f"{REBUILD_DB}{suffix}").unlink(missing_ok=True)
    shutil.copyfile(SNAPSHOT, REBUILD_DB)
    os.chmod(REBUILD_DB, 0o644)
    return restore_records(REBUILD_DB, saved)


def prune() -> dict:
    conn = sqlite3.connect(REBUILD_DB)
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        stats = {
            "deleted_articles": conn.execute("DELETE FROM daily_articles").rowcount,
            "deleted_editions": conn.execute("DELETE FROM daily_editions").rowcount,
        }
        conn.execute("UPDATE source_items SET cluster_id = NULL, duplicate_of_id = NULL")
        stats["deleted_clusters"] = conn.execute("DELETE FROM story_clusters").rowcount
        stats["deleted_late_items"] = conn.execute(
            "DELETE FROM source_items WHERE first_seen_at > ?", (CUTOFF_SQL,)
        ).rowcount
        stats["remaining_items"] = conn.execute("SELECT COUNT(*) FROM source_items").fetchone()[0]
        conn.commit()
        problems = conn.execute("PRAGMA foreign_key_check").fetchall()
        assert not [p for p in problems if p[0] in ("source_items", "daily_articles", "story_clusters")], problems
    finally:
        conn.close()
    return stats


def recompute() -> int:
    from sqlalchemy import select

    from reddit_tracker.collection.collector import recompute_duplicates
    from reddit_tracker.db import session_scope
    from reddit_tracker.models import SourceItem

    with session_scope() as session:
        return recompute_duplicates(list(session.scalars(select(SourceItem))))


def build_writer(mode: str, max_attempts: int):
    from llm_recorder import RecordingCodexClient, cli_version

    from reddit_tracker.daily.writer import DailyWriter
    from reddit_tracker.llm.codex import CodexClient

    if mode == "template":
        return None, None
    codex = CodexClient(purpose="daily")
    if not Path(codex.binary).exists():
        raise SystemExit(f"找不到 codex：{codex.binary}；改用 --writer template")
    recorder = RecordingCodexClient(
        codex, db_path=REBUILD_DB, ledgers=LEDGERS, version=cli_version(codex.binary),
        role="writer", run_variant="rebuild-3.8", edition_date=EDITION_DATE, max_attempts=max_attempts,
    )
    return DailyWriter("codex", client=recorder), recorder


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--writer", choices=("codex", "template"), default="codex")
    parser.add_argument("--max-attempts", type=int, default=60, help="整個任務真 Codex 嘗試上限（所有帳本加總）")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s | %(message)s")
    if not SNAPSHOT.exists():
        raise SystemExit(f"母本不存在：{SNAPSHOT}")

    configure_env()
    from reddit_tracker.daily import run

    kept = fresh_copy()
    print(f"[rebuild] copied snapshot → {REBUILD_DB.relative_to(ROOT)}（沿用 {kept} 筆 llm_records）")
    print(f"[rebuild] prune: {prune()}")
    print(f"[rebuild] recompute_duplicates: {recompute()} duplicates")
    print(f"[rebuild] recluster(now={NOW.isoformat()}): {run.recluster(NOW)}")

    market = old_market()
    run.fetch_market_box = lambda: market  # 10/27 當期的數據欄，不連網
    run.RETRY_DELAY_SECONDS = 2.0
    writer, recorder = build_writer(args.writer, args.max_attempts)
    edition_id = run.prepare_daily(EDITION_DATE, now=NOW, writer=writer, writer_mode=args.writer, refresh=True)

    from reddit_tracker.db import session_scope
    from reddit_tracker.models import DailyEdition

    with session_scope() as session:
        edition = session.get(DailyEdition, edition_id)
        stats = {k: v for k, v in (edition.stats or {}).items() if k not in ("market", "merged_groups")}
        print(f"[rebuild] edition={edition.id} status={edition.status} writer={edition.writer} html={edition.html_path}")
        print(f"[rebuild] stats={json.dumps(stats, ensure_ascii=False)}")
    if recorder is not None:
        print(f"[rebuild] codex attempts this run={recorder.attempts} reused={recorder.reused}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

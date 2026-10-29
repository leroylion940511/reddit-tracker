"""替回歸集錄 LLM 回應：走 `tests/regression/rebuild.py` 同一條路徑（逐輪聚合＋`1027_merges.json`
重播編輯會議），撰稿請求先查錄音／帳本，沒有才真的呼叫 Codex 並記進 `llm_records`。

    uv run python scripts/record_regression_1027.py            # 錄音（會呼叫真 Codex）
    uv run python scripts/record_regression_1027.py --check    # 只重播，列出缺的 request_hash（不呼叫）

回歸 runner 是逐輪聚合，和步驟 3.8 一次重聚的稿件不同，request_hash 也不同，所以要另外錄。
工作目錄 `data/work/1027_regression_record/`（runner 的 tmp SQLite 放這裡，`llm_records` 也在這個複本裡；
重跑時舊的錄音列會搬到新檔）。結束後把所有帳本 ok 的紀錄匯出到
`tests/regression/fixtures/1027_llm_records.json`。
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "scripts")]

import rebuild_1027 as rb  # noqa: E402

WORKDIR = rb.WORK / "1027_regression_record"
LEDGER_DB = WORKDIR / "1027_rebuild.db"  # runner 自己建的 SQLite；檔名由 rebuild_view 決定
FIXTURE = ROOT / "tests/regression/fixtures/1027_llm_records.json"
assert LEDGER_DB in rb.LEDGERS


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true", help="只用錄音重播，不呼叫 Codex")
    parser.add_argument("--max-attempts", type=int, default=60)
    args = parser.parse_args(argv)

    os.environ["LLM_QUOTA_STATE_PATH"] = str(rb.QUOTA_STATE)
    os.environ["DATABASE_URL"] = f"sqlite:///{LEDGER_DB}"
    from llm_recorder import RecordingCodexClient, cli_version, export_ok_records, restore_records, saved_records

    from reddit_tracker.config import get_settings
    from reddit_tracker.llm.codex import CodexClient
    from reddit_tracker.llm.replay import ReplayClient, ReplayMissing, load_records

    get_settings.cache_clear()
    assert Path(get_settings().llm_quota_state_path) == rb.QUOTA_STATE
    from tests.regression import rebuild as runner
    from tests.regression.checks import referenced_titles

    saved = saved_records(LEDGER_DB)
    if WORKDIR.exists():
        shutil.rmtree(WORKDIR)
    WORKDIR.mkdir(parents=True)
    restore_records(LEDGER_DB, saved)  # 先建 llm_records（新欄位），runner 的 create_all 會略過它

    recorder = None
    if not args.check:
        codex = CodexClient(purpose="daily")
        recorder = RecordingCodexClient(
            codex, db_path=LEDGER_DB, ledgers=rb.LEDGERS, version=cli_version(codex.binary),
            role="writer", run_variant="regression-runner", edition_date=rb.EDITION_DATE,
            max_attempts=args.max_attempts,
        )

    class RecordOnMiss(ReplayClient):
        """先查錄音檔；沒有就交給 recorder（它會再查帳本、真的呼叫並記錄）。"""

        def complete(self, **kwargs):
            try:
                return super().complete(**kwargs)
            except ReplayMissing:
                if recorder is None:
                    raise
                missed = self.misses.pop()
                try:
                    return recorder.complete(**kwargs)
                except Exception:
                    self.misses.append(missed)
                    raise

    runner.ReplayClient = RecordOnMiss
    needed = {t for case in runner.load_cases() for t in referenced_titles(case)}
    view = runner.rebuild_view(WORKDIR, needed)
    misses = list(dict.fromkeys(view.replay_misses or []))
    writers = {}
    for story in view.published:
        writers[story.writer] = writers.get(story.writer, 0) + 1
    print(f"[record] published={len(view.published)} writers={writers} misses={len(misses)}")
    for key in misses:
        print(f"[record] miss {key}")
    if recorder is not None:
        print(f"[record] codex attempts this run={recorder.attempts} reused={recorder.reused}")
        count = export_ok_records([p for p in rb.LEDGERS if p.exists()], FIXTURE)
        print(f"[record] exported {count} ok records → {FIXTURE.relative_to(ROOT)} ({FIXTURE.stat().st_size} bytes)")
        print(f"[record] fixture now replays {len(load_records(FIXTURE))} request_hash")
    return 1 if misses else 0


if __name__ == "__main__":
    raise SystemExit(main())

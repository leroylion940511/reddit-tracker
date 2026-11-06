"""替 E11（莫德納癌症疫苗）錄 M 組回應。pytest 不呼叫這支的 `--live`。

    uv run python scripts/record_e11.py --live     # Mac 上真 Codex，只寫 data/work 複本
    uv run python scripts/record_e11.py --check    # 只重播 fixture；沒有錄音就停，不呼叫 Codex

`--live` 做的事：
1. 用已 commit 的 `tests/regression/fixtures/1027_items.json.xz` 在
   `data/work/1027_e11.db` 逐輪聚合（與回歸 runner 相同）。不讀 production DB、不讀 `.env`。
2. 用 `cases/E11.json` 的 event_titles 找到那一則（MarketWatch 單一來源，財經改判國際）。
3. 只跑這則：記者 → 程式查核（有可疑來源或對不上的數字才叫查核員）→ 放上頭版給文稿編輯。
4. 已有的 request_hash 直接重播。新的 Codex CLI 呼叫上限 5（關掉自動重試，所以一角色一次）。
   額度檔是 `data/work/llm-quota-e11.json`，與 production、`llm-quota-merge.json` 分開。
5. 記者與文稿編輯都有 ok 紀錄才寫：
   `tests/regression/fixtures/1027_e11_evidence.json`
   `tests/regression/fixtures/1027_e11_records.json`

重錄（提示詞或證據包改了）：刪掉上面的 DB、額度檔與兩個 fixture 再 `--live`。
Codex binary 用設定預設 `/opt/homebrew/bin/codex`（0.166.0）。路徑不同就在指令外設 `CODEX_BIN`，
不要把 token 放進指令，也不要靠 `.env`（這支腳本不載入它）。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tests.regression import e11_replay as e11  # noqa: E402

WORK = ROOT / "data" / "work"
WORK_DB = WORK / "1027_e11.db"
QUOTA = WORK / "llm-quota-e11.json"
SITE = WORK / "e11-site"


def require_work_db(path: Path) -> Path:
    path = path.resolve()
    work = WORK.resolve()
    if not path.is_relative_to(work):
        raise SystemExit(f"只寫 data/work 複本，拒絕：{path}")
    if path.name in {"reddit_tracker.db", "prod.db"}:
        raise SystemExit(f"拒絕 production 檔名：{path.name}")
    return path


def _configure(path: Path) -> None:
    """一定要在讀 settings／建立 CodexClient 之前。不載入 .env，避免 production DATABASE_URL。"""
    os.environ["REDDIT_TRACKER_NO_DOTENV"] = "1"
    os.environ["DATABASE_URL"] = f"sqlite:///{path}"
    os.environ["LLM_QUOTA_STATE_PATH"] = str(QUOTA)
    os.environ["LLM_DAILY_LIMIT"] = str(e11.MAX_ATTEMPTS)
    os.environ["DAILY_SITE_DIR"] = str(SITE)
    os.environ["DAILY_MODE"] = "mas"
    from reddit_tracker.config import get_settings

    get_settings.cache_clear()
    settings = get_settings()
    if settings.database_url != f"sqlite:///{path}":
        raise SystemExit(f"DATABASE_URL 沒有指到複本：{settings.database_url}")
    if Path(settings.llm_quota_state_path) != QUOTA:
        raise SystemExit(f"額度檔沒有指到 data/work：{settings.llm_quota_state_path}")


class _Live:
    """先查 fixture 與複本帳本，沒有才呼叫 Codex。每次 complete 最多一次 CLI（max_retries=0）。"""

    logs_attempts = True

    def __init__(self, db_path: Path) -> None:
        from reddit_tracker.llm.codex import CodexClient
        from reddit_tracker.llm.records import (
            attempts_used,
            cli_version,
            lookup_ok,
            model_version,
        )
        from reddit_tracker.llm.replay import (
            ReplayResult,
            load_records,
            prompt_text,
            request_hash,
        )

        self._ReplayResult = ReplayResult
        self._lookup_ok = lookup_ok
        self._attempts_used = attempts_used
        self._request_hash = request_hash
        self._prompt_text = prompt_text
        self.db_path = db_path
        self.codex = CodexClient(max_retries=0, purpose="daily")
        self.model = self.codex.model
        self.codex.model_version = model_version(
            self.codex, cli_version(self.codex.binary)
        )
        self.records = load_records(e11.RECORDS) if e11.RECORDS.is_file() else {}
        self.attempts = 0
        self.reused = 0
        self.failed = False
        self.blocked = False

    def complete(self, **kwargs):
        key = self._request_hash(
            system=kwargs["system"],
            prompt=self._prompt_text(kwargs["messages"]),
            model=self.model,
            schema=kwargs.get("json_schema"),
        )
        cached = self.records.get(key)
        if cached is None:
            cached = self._lookup_ok([self.db_path], key)
        if cached is not None:
            self.reused += 1
            return self._ReplayResult(cached)
        used = self._attempts_used([self.db_path])
        if used >= e11.MAX_ATTEMPTS:
            self.blocked = True
            from reddit_tracker.llm.records import AttemptBudgetExhausted

            raise AttemptBudgetExhausted(f"E11 真 Codex 已達上限 {e11.MAX_ATTEMPTS}")
        self.attempts += 1
        print(
            f"[e11] live {self.attempts} ledger {used + 1}/{e11.MAX_ATTEMPTS} {key[:12]}",
            flush=True,
        )
        try:
            return self.codex.complete(**kwargs)
        except Exception:
            self.failed = True
            raise


def _export(db_path: Path, story: dict) -> None:
    from reddit_tracker.llm.records import export_ok_records

    e11.EVIDENCE.write_text(
        json.dumps(story, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )
    count = export_ok_records([db_path], e11.RECORDS)
    print(f"[e11] exported {count} ok records → {e11.RECORDS.relative_to(ROOT)}")
    print(f"[e11] evidence → {e11.EVIDENCE.relative_to(ROOT)}")


def live(db_path: Path | None = None) -> int:
    from sqlalchemy import create_engine, select
    from sqlalchemy.orm import Session

    from reddit_tracker.llm.records import bind_log_session
    from reddit_tracker.models import LLMRecord

    path = require_work_db(db_path or WORK_DB)
    _configure(path)
    print(
        f"[e11] db={path.relative_to(ROOT)} quota={QUOTA.relative_to(ROOT)} cap={e11.MAX_ATTEMPTS}"
    )
    story = e11.prepare_story(path)
    print(f"[e11] {story['note']}")
    engine = create_engine(f"sqlite:///{path}", future=True)
    client = _Live(path)
    with Session(engine, expire_on_commit=False) as session:
        with bind_log_session(session):
            version = e11.run_roles(
                session,
                client,
                spec=story["spec"],
                evidence=e11.evidence_items(story["evidence"]),
            )
        session.commit()
        roles = {
            row.role
            for row in session.scalars(select(LLMRecord).where(LLMRecord.ok.is_(True)))
        }
        headline = version.headline
    engine.dispose()
    problems = e11.headline_violations(headline)
    print(
        f"[e11] attempts={client.attempts} reused={client.reused} roles={sorted(roles)} headline={headline!r}"
    )
    if (
        client.failed
        or client.blocked
        or "reporter" not in roles
        or "copy_editor" not in roles
    ):
        print(
            "[e11] 不匯出：記者或文稿編輯沒有 ok 紀錄，或呼叫失敗／超過上限。已 ok 的 hash 留在複本，可再跑 --live。"
        )
        return 1
    _export(path, story)
    if problems:
        print("[e11] 已匯出，但標題仍符合禁止樣式：")
        for pattern in problems:
            print(f"[e11]   {pattern}")
        return 1
    print(f"[e11] 重播檢查：{e11.CHECK_COMMAND}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--live", action="store_true", help="允許呼叫本機 Codex（預設只重播）"
    )
    parser.add_argument("--check", action="store_true", help="只重播，不呼叫 Codex")
    args = parser.parse_args(argv)
    if args.live and args.check:
        raise SystemExit("--live 與 --check 只能擇一")
    if args.live:
        return live()
    return e11.check_recorded()


if __name__ == "__main__":
    raise SystemExit(main())

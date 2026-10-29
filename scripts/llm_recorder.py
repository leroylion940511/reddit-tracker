"""在 `data/work` 複本上錄真 Codex 呼叫（手冊步驟 3 第 8 點、強制指令 3）。

正式的 `llm_records` 表／model／`llm/records.py` 由步驟 6–7 的另一個分支負責；這裡不碰
`models.py`、migration、`llm/codex.py`，只在**複本** SQLite 裡 `CREATE TABLE IF NOT EXISTS`
（母本已有舊版 `llm_records` 表時補欄位），欄位與那個分支的 migration 相容：

    id, provider, model, model_version, purpose, request_hash, prompt_text, response_text,
    latency_ms, ok, error, role, run_variant, edition_date, story_id,
    input_tokens, output_tokens, cached_tokens, called_at

`RecordingCodexClient`：
- 介面與 `CodexClient.complete` 相同；`request_hash` 一律用 `llm/replay.request_hash`。
- 同一個 request_hash 在任何一本帳（`ledgers`）已有 ok 回應就直接重用，不呼叫。
- 自己做重試迴圈，**每一次 subprocess 嘗試**（含重試、失敗）都寫一列。
- 額度：每次嘗試前照常扣 `ModelQuotaGuard`（state 檔由 `LLM_QUOTA_STATE_PATH` 指定），
  另外有整個任務的硬上限 `max_attempts`（所有帳本的 codex 列加總）。
"""

from __future__ import annotations

import json
import sqlite3
import subprocess
import time
from datetime import date, datetime, timezone
from pathlib import Path

from reddit_tracker.llm.codex import CodexClient, CodexError, CodexUnsafeOutput
from reddit_tracker.llm.quota import QuotaExhausted
from reddit_tracker.llm.replay import ReplayResult, prompt_text, request_hash

PROVIDER = "codex"
COLUMNS = {
    "id": "INTEGER PRIMARY KEY",
    "provider": "VARCHAR(32) NOT NULL",
    "model": "VARCHAR(64) NOT NULL",
    "purpose": "VARCHAR(32) NOT NULL",
    "input_tokens": "INTEGER",
    "output_tokens": "INTEGER",
    "cached_tokens": "INTEGER",
    "cost_usd": "NUMERIC(10, 6)",
    "called_at": "DATETIME NOT NULL DEFAULT (CURRENT_TIMESTAMP)",
    "context_ref": "JSON",
    "request_hash": "VARCHAR(64)",
    "prompt_text": "TEXT",
    "response_text": "TEXT",
    "latency_ms": "INTEGER",
    "ok": "BOOLEAN",
    "error": "TEXT",
    "role": "VARCHAR(32)",
    "run_variant": "VARCHAR(16)",
    "edition_date": "DATE",
    "story_id": "INTEGER",
    "model_version": "TEXT",
}
# 匯出給回歸集的欄位（不含 prompt 以外的任何本機資訊；prompt 只有新聞標題與摘要）
EXPORT_FIELDS = (
    "request_hash", "response_text", "ok", "provider", "model", "model_version", "purpose", "role",
    "run_variant", "edition_date", "latency_ms", "input_tokens", "output_tokens", "cached_tokens", "called_at",
)


class AttemptBudgetExhausted(QuotaExhausted):
    """整個任務的真 Codex 嘗試上限用完；當成額度用完處理（該版退模板稿、不重試）。"""


def ensure_llm_records(db_path: str | Path) -> None:
    conn = sqlite3.connect(db_path)
    try:
        cols = ", ".join(f"{name} {kind}" for name, kind in COLUMNS.items())
        conn.execute(f"CREATE TABLE IF NOT EXISTS llm_records ({cols})")
        existing = {row[1] for row in conn.execute("PRAGMA table_info(llm_records)")}
        for name, kind in COLUMNS.items():
            if name not in existing:
                conn.execute(f"ALTER TABLE llm_records ADD COLUMN {name} {kind.replace(' NOT NULL', '')}")
        conn.execute("CREATE INDEX IF NOT EXISTS ix_llm_records_request_hash ON llm_records (request_hash)")
        conn.commit()
    finally:
        conn.close()


def cli_version(binary: str) -> str:
    """`codex --version`（不是 LLM 呼叫）。"""
    try:
        out = subprocess.run([binary, "--version"], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return "codex-cli unknown"
    return (out.stdout or out.stderr).strip() or "codex-cli unknown"


def model_version(codex: CodexClient, version: str) -> str:
    return f"{codex.model} | {version} | reasoning_effort={codex.reasoning_effort}"


def _has_table(conn: sqlite3.Connection) -> bool:
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='llm_records'").fetchone() is not None


def _columns(conn: sqlite3.Connection) -> set[str]:
    return {row[1] for row in conn.execute("PRAGMA table_info(llm_records)")}


def lookup_ok(ledgers: list[Path], key: str) -> str | None:
    for path in ledgers:
        if not Path(path).exists():
            continue
        conn = sqlite3.connect(path)
        try:
            if not _has_table(conn) or "request_hash" not in _columns(conn):
                continue
            row = conn.execute(
                "SELECT response_text FROM llm_records WHERE request_hash = ? AND ok = 1"
                " AND response_text IS NOT NULL ORDER BY id DESC LIMIT 1",
                (key,),
            ).fetchone()
        finally:
            conn.close()
        if row:
            return row[0]
    return None


def attempts_used(ledgers: list[Path]) -> int:
    """所有帳本裡本任務錄的 codex 嘗試數（有 request_hash 的列；母本那筆舊紀錄不算）。"""
    total = 0
    for path in ledgers:
        if not Path(path).exists():
            continue
        conn = sqlite3.connect(path)
        try:
            if _has_table(conn) and "request_hash" in _columns(conn):
                total += conn.execute(
                    "SELECT COUNT(*) FROM llm_records WHERE provider = ? AND request_hash IS NOT NULL", (PROVIDER,)
                ).fetchone()[0]
        finally:
            conn.close()
    return total


class RecordingCodexClient:
    """包住 `CodexClient`：先查帳本重用，沒有才真的呼叫；每次嘗試寫一列 `llm_records`。"""

    def __init__(
        self,
        codex: CodexClient,
        *,
        db_path: str | Path,
        ledgers: list[str | Path] = (),
        version: str,
        role: str,
        run_variant: str,
        edition_date: date,
        max_attempts: int,
        log=print,
    ) -> None:
        self.codex = codex
        self.db_path = Path(db_path)
        self.ledgers = list(dict.fromkeys([self.db_path, *map(Path, ledgers)]))
        self.model_version = model_version(codex, version)
        self.role = role
        self.run_variant = run_variant
        self.edition_date = edition_date
        self.max_attempts = max_attempts
        self.log = log
        self.attempts = 0
        self.reused = 0
        ensure_llm_records(self.db_path)

    @property
    def model(self) -> str:
        return self.codex.model

    def complete(
        self,
        *,
        system: str,
        messages: list[dict],
        max_output_tokens: int,
        temperature: float,
        json_mode: bool = False,
        json_schema: dict | None = None,
    ) -> ReplayResult:
        del max_output_tokens, temperature
        prompt = prompt_text(messages)
        key = request_hash(system=system, prompt=prompt, model=self.model, schema=json_schema)
        cached = lookup_ok(self.ledgers, key)
        if cached is not None:
            self.reused += 1
            self.log(f"[recorder] reuse {key[:12]}")
            return ReplayResult(cached)
        # 送給 codex 的內容與 CodexClient.complete 相同
        full_prompt = f"{system}\n\n{prompt}"
        if json_mode and json_schema is None:
            full_prompt += "\n\n只輸出 JSON。"
        # 編輯會議（find_same_events，GROUPS schema）記成 desk，撰稿記成建構時給的 role
        role = "desk" if json_schema and "groups" in json_schema.get("properties", {}) else self.role
        retries = self.codex.max_retries
        for attempt in range(retries + 1):
            used = attempts_used(self.ledgers)
            if used >= self.max_attempts:
                raise AttemptBudgetExhausted(f"真 Codex 嘗試已達上限 {self.max_attempts}")
            self.codex.guard.acquire(model=self.model, purpose=self.codex.purpose)
            self.attempts += 1
            started = time.perf_counter()
            self.log(f"[recorder] codex attempt #{used + 1} {role} {key[:12]} …", flush=True)
            try:
                result = self.codex._run_once(full_prompt, json_schema)
            except CodexError as exc:
                self._write(key, prompt, None, started, role, ok=False, error=f"{type(exc).__name__}: {exc}")
                self.log(f"[recorder] failed: {type(exc).__name__}: {str(exc)[:200]}", flush=True)
                if isinstance(exc, CodexUnsafeOutput) or attempt == retries:
                    raise
                continue
            self._write(key, prompt, result, started, role, ok=True, error=None)
            self.log(f"[recorder] ok in {time.perf_counter() - started:.0f}s", flush=True)
            return ReplayResult(result.content, result.input_tokens, result.output_tokens, result.cached_tokens)
        raise AssertionError("unreachable")  # pragma: no cover

    def _write(self, key, prompt, result, started, role, *, ok, error) -> None:
        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute(
                "INSERT INTO llm_records (provider, model, model_version, purpose, request_hash, prompt_text,"
                " response_text, latency_ms, ok, error, role, run_variant, edition_date, story_id,"
                " input_tokens, output_tokens, cached_tokens, called_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    PROVIDER, self.model, self.model_version, self.codex.purpose, key, prompt,
                    result.content if result else None, int((time.perf_counter() - started) * 1000),
                    1 if ok else 0, error and error[:2000], role, self.run_variant,
                    self.edition_date.isoformat(), None,
                    getattr(result, "input_tokens", None), getattr(result, "output_tokens", None),
                    getattr(result, "cached_tokens", None),
                    datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S.%f"),
                ),
            )
            conn.commit()
        finally:
            conn.close()


def export_ok_records(ledgers: list[str | Path], out: str | Path) -> int:
    """把帳本裡 ok 的紀錄匯出成回歸集錄音檔（`llm/replay.load_records` 讀得懂）；同 hash 只留最後一筆。"""
    rows: dict[str, dict] = {}
    for path in ledgers:
        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        try:
            if not _has_table(conn) or "request_hash" not in _columns(conn):
                continue
            for row in conn.execute(
                f"SELECT {', '.join(EXPORT_FIELDS)} FROM llm_records"
                " WHERE ok = 1 AND request_hash IS NOT NULL AND response_text IS NOT NULL ORDER BY id"
            ):
                record = dict(row)
                record["ok"] = bool(record["ok"])
                rows[record["request_hash"]] = record
        finally:
            conn.close()
    ordered = sorted(rows.values(), key=lambda r: (r["called_at"] or "", r["request_hash"]))
    Path(out).write_text(json.dumps(ordered, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return len(ordered)


def saved_records(path: str | Path) -> list[dict]:
    """重建複本前先把本任務錄的列（有 request_hash 的）讀出來，重建後用 `restore_records` 放回。"""
    path = Path(path)
    if not path.exists():
        return []
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        if not _has_table(conn) or "request_hash" not in _columns(conn):
            return []
        return [dict(r) for r in conn.execute("SELECT * FROM llm_records WHERE request_hash IS NOT NULL ORDER BY id")]
    finally:
        conn.close()


def restore_records(path: str | Path, rows: list[dict]) -> int:
    ensure_llm_records(path)
    conn = sqlite3.connect(path)
    try:
        for row in rows:
            row = {k: v for k, v in row.items() if k != "id"}
            conn.execute(
                f"INSERT INTO llm_records ({', '.join(row)}) VALUES ({', '.join('?' * len(row))})", list(row.values())
            )
        conn.commit()
    finally:
        conn.close()
    return len(rows)

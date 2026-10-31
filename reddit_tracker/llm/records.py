"""每一次 LLM 嘗試寫進 `llm_records`。重播用 `request_hash`，找不到就不呼叫模型。

Codex／Gemini client 在每次 subprocess／HTTP 嘗試結束時呼叫 `note_attempt`（含失敗與重試）。
沒有綁定 session 時不寫資料庫，單元測試不會碰到預設的 SQLite 檔。
`complete_logged` 給不自己寫紀錄的 client（fake、replay、腳本）：先看同一個 request_hash
是否已有 ok 的回應，有就直接用，不再花額度。
"""

from __future__ import annotations

import time
import json
import sqlite3
from pathlib import Path

from .quota import QuotaExhausted
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, replace
from datetime import date, datetime, timezone
from typing import Iterator

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import LLMRecord
from .replay import ReplayResult, prompt_text, request_hash


@dataclass(frozen=True)
class LogMeta:
    role: str | None = None
    run_variant: str | None = None
    edition_date: date | None = None
    story_id: int | None = None
    purpose: str | None = None


_factory: ContextVar = ContextVar("llm_log_factory", default=None)
_meta: ContextVar[LogMeta] = ContextVar("llm_log_meta", default=LogMeta())


@contextmanager
def bind_log_factory(factory) -> Iterator[None]:
    """`factory()` 是 context manager，yield 一個 Session。每次嘗試用它寫一列。"""
    token = _factory.set(factory)
    try:
        yield
    finally:
        _factory.reset(token)


@contextmanager
def bind_log_session(session: Session) -> Iterator[None]:
    """寫進呼叫端自己的 session（flush，不 commit）。"""

    @contextmanager
    def factory():
        yield session

    with bind_log_factory(factory):
        yield


@contextmanager
def llm_log_meta(**kwargs) -> Iterator[None]:
    token = _meta.set(replace(_meta.get(), **kwargs))
    try:
        yield
    finally:
        _meta.reset(token)


def note_attempt(
    *,
    provider: str,
    model: str,
    model_version: str,
    purpose: str,
    system: str,
    messages: list[dict],
    schema: dict | None,
    ok: bool,
    response_text: str | None,
    error: str | None,
    latency_ms: int,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    cached_tokens: int | None = None,
) -> int | None:
    factory = _factory.get()
    if factory is None:
        return None
    meta = _meta.get()
    prompt = prompt_text(messages)
    digest = request_hash(system=system, prompt=prompt, model=model, schema=schema)
    row = LLMRecord(
        provider=provider,
        model=model[:64],
        model_version=model_version,
        purpose=(meta.purpose or purpose)[:32],
        request_hash=digest,
        prompt_text=prompt,
        response_text=response_text,
        latency_ms=latency_ms,
        ok=ok,
        error=(error or None) and str(error)[:2000],
        role=meta.role,
        run_variant=meta.run_variant,
        edition_date=meta.edition_date,
        story_id=meta.story_id,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cached_tokens=cached_tokens,
        called_at=datetime.now(timezone.utc),
    )
    with factory() as session:
        session.add(row)
        session.flush()
        return row.id


def cached_ok_response(session: Session, *, system: str, messages: list[dict], model: str, schema: dict | None) -> str | None:
    digest = request_hash(system=system, prompt=prompt_text(messages), model=model, schema=schema)
    row = session.scalar(
        select(LLMRecord)
        .where(LLMRecord.request_hash == digest, LLMRecord.ok.is_(True), LLMRecord.response_text.is_not(None))
        .order_by(LLMRecord.id.desc())
    )
    return None if row is None else row.response_text


def complete_logged(client, session: Session, **kwargs) -> str:
    """呼叫 `client.complete`。已錄過的 request_hash 直接重播。自己會寫紀錄的 client 不重複寫。"""
    system = kwargs["system"]
    messages = kwargs["messages"]
    schema = kwargs.get("json_schema")
    model = getattr(client, "model", "fake")
    cached = cached_ok_response(session, system=system, messages=messages, model=model, schema=schema)
    if cached is not None:
        return cached
    if getattr(client, "logs_attempts", False):
        return client.complete(**kwargs).content
    started = time.perf_counter()
    try:
        result = client.complete(**kwargs)
    except Exception as exc:
        note_attempt(
            provider=type(client).__name__,
            model=model,
            model_version=getattr(client, "model_version", model),
            purpose=getattr(client, "purpose", "mas"),
            system=system,
            messages=messages,
            schema=schema,
            ok=False,
            response_text=None,
            error=f"{type(exc).__name__}: {exc}",
            latency_ms=int((time.perf_counter() - started) * 1000),
        )
        raise
    note_attempt(
        provider=type(client).__name__,
        model=model,
        model_version=getattr(client, "model_version", model),
        purpose=getattr(client, "purpose", "mas"),
        system=system,
        messages=messages,
        schema=schema,
        ok=True,
        response_text=result.content,
        error=None,
        latency_ms=int((time.perf_counter() - started) * 1000),
        input_tokens=getattr(result, "input_tokens", None),
        output_tokens=getattr(result, "output_tokens", None),
        cached_tokens=getattr(result, "cached_tokens", None),
    )
    return result.content


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
    """`codex --version`（不是 LLM 呼叫），格式 `codex-cli 0.166.0`；讀不到回 `codex-cli unknown`。"""
    from .codex_version import probe_cli_version

    version = probe_cli_version(binary)
    return f"codex-cli {version}" if version else "codex-cli unknown"


def model_version(codex, version: str) -> str:
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
    """Cache adapter; CodexClient alone retries, charges quota and calls note_attempt."""
    logs_attempts = True

    def __init__(self, codex, *, db_path, ledgers=(), version, role, run_variant,
                 edition_date, max_attempts, log=print):
        self.codex = codex
        self.db_path = Path(db_path)
        self.ledgers = list(dict.fromkeys([self.db_path, *map(Path, ledgers)]))
        self.codex.model_version = model_version(codex, version)
        self.role, self.run_variant, self.edition_date = role, run_variant, edition_date
        self.max_attempts, self.log = max_attempts, log
        self.attempts = self.reused = 0
        ensure_llm_records(self.db_path)

    @property
    def model(self):
        return self.codex.model

    @property
    def guard(self):
        return self.codex.guard

    def complete(self, **kwargs):
        key = request_hash(system=kwargs["system"], prompt=prompt_text(kwargs["messages"]),
                           model=self.model, schema=kwargs.get("json_schema"))
        cached = lookup_ok(self.ledgers, key)
        if cached is not None:
            self.reused += 1
            return ReplayResult(cached)
        from sqlalchemy import create_engine
        engine = create_engine(f"sqlite:///{self.db_path}")
        original_guard = self.codex.guard
        owner = self

        class BudgetGuard:
            def acquire(self, **kw):
                if attempts_used(owner.ledgers) >= owner.max_attempts:
                    raise AttemptBudgetExhausted(f"真 Codex 嘗試已達上限 {owner.max_attempts}")
                original_guard.acquire(**kw)
                owner.attempts += 1
                owner.log(f"[recorder] attempt {owner.attempts} {key[:12]}", flush=True)

        @contextmanager
        def factory():
            with Session(engine) as session:
                with session.begin():
                    yield session

        schema = kwargs.get("json_schema") or {}
        role = "desk" if "groups" in schema.get("properties", {}) else self.role
        self.codex.guard = BudgetGuard()
        try:
            with bind_log_factory(factory), llm_log_meta(role=role, run_variant=self.run_variant,
                                                        edition_date=self.edition_date):
                return self.codex.complete(**kwargs)
        finally:
            self.codex.guard = original_guard
            engine.dispose()


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

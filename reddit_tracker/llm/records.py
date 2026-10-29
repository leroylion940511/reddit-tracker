"""每一次 LLM 嘗試寫進 `llm_records`。重播用 `request_hash`，找不到就不呼叫模型。

Codex／Gemini client 在每次 subprocess／HTTP 嘗試結束時呼叫 `note_attempt`（含失敗與重試）。
沒有綁定 session 時不寫資料庫，單元測試不會碰到預設的 SQLite 檔。
`complete_logged` 給不自己寫紀錄的 client（fake、replay、腳本）：先看同一個 request_hash
是否已有 ok 的回應，有就直接用，不再花額度。
"""

from __future__ import annotations

import time
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, replace
from datetime import date, datetime, timezone
from typing import Iterator

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import LLMRecord
from .replay import prompt_text, request_hash


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

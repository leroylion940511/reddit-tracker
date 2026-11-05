"""06:00 準備的 LLM 截止時間：過了就不再呼叫模型，各角色照既有規則降級（模板稿）。

2026-11-05 M 組記者兩次卡滿 `CODEX_TIMEOUT_SECONDS`=300 秒，靠重試救回，整期 06:15 才畫完。
每次嘗試都可能卡滿逾時，額度 60 格最壞要 5 小時，會趕不上 08:35 發行。截止時間用 context
variable 綁在準備那一段（`llm_deadline`），每次嘗試開始前檢查剩餘秒數，subprocess 的逾時也不超過
剩餘秒數，所以 LLM 呼叫不會跑過截止。沒有綁截止時間（CLI、測試）就照舊只看單次逾時。
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import date, datetime, time, timezone
from zoneinfo import ZoneInfo

# 剩不到這麼多秒就不開新的嘗試（M 組一次呼叫平均 5–10 秒，P 撰稿 15–45 秒）
MIN_ATTEMPT_SECONDS = 20.0

_deadline: ContextVar[datetime | None] = ContextVar("llm_deadline", default=None)


class DeadlinePassed(RuntimeError):
    """離截止時間太近，不再呼叫模型。不重試、不扣額度、不寫 llm_records。"""


@contextmanager
def llm_deadline(at: datetime | None) -> Iterator[datetime | None]:
    """在這段期間內 LLM 嘗試不能跑過 `at`；巢狀時取較早的那個。`at` 是 None 就不改。"""
    outer = _deadline.get()
    effective = at if outer is None else (outer if at is None else min(outer, at))
    token = _deadline.set(effective)
    try:
        yield effective
    finally:
        _deadline.reset(token)


def current_deadline() -> datetime | None:
    return _deadline.get()


def deadline_reached(*, now: datetime | None = None) -> bool:
    """離截止不到一次嘗試的時間（沒綁截止＝False）。"""
    deadline = _deadline.get()
    return deadline is not None and (deadline - (now or datetime.now(timezone.utc))).total_seconds() < MIN_ATTEMPT_SECONDS


def attempt_timeout(timeout: float, *, now: datetime | None = None) -> float:
    """這次嘗試能用的逾時秒數＝min(單次逾時, 離截止的秒數)；剩不到 MIN_ATTEMPT_SECONDS 就丟 DeadlinePassed。"""
    deadline = _deadline.get()
    if deadline is None:
        return timeout
    left = (deadline - (now or datetime.now(timezone.utc))).total_seconds()
    if left < MIN_ATTEMPT_SECONDS:
        raise DeadlinePassed(f"離準備截止 {deadline.isoformat(timespec='minutes')} 只剩 {max(left, 0):.0f} 秒，不再呼叫模型")
    return min(timeout, left)


def deadline_on(day: date, hhmm: str, tz: str) -> datetime:
    """`day` 當地 `hhmm`（例如 "08:20"）的 aware datetime。"""
    hour, minute = (int(part) for part in hhmm.split(":"))
    return datetime.combine(day, time(hour, minute), tzinfo=ZoneInfo(tz))

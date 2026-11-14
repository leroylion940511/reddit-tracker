"""訊息白名單、工具白名單、搶訊息。不合法的訊息照樣入表，status=rejected。"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from ...models import AgentMessage
from ..store import hold_story, latest_version

MAX_MESSAGES = 80
MAX_CHALLENGES = 2

ROLES = (
    "eic", "section_editor", "reporter", "fact_checker", "copy_editor", "layout_editor", "system", "human",
)

# (sender, type)。程式強制，不靠提示詞。
ALLOWED = frozenset({
    ("section_editor", "PITCH"),
    ("fact_checker", "CHALLENGE"),
    ("copy_editor", "CHALLENGE"),
    ("eic", "REQUEST_REVISION"),
    ("layout_editor", "REQUEST_REVISION"),
    ("reporter", "REVISION_DONE"),
    ("reporter", "REBUT"),
    ("fact_checker", "HOLD"),
    ("system", "HOLD"),
    ("human", "HOLD"),
    ("system", "RELEASE"),
    ("human", "RELEASE"),
    ("layout_editor", "PAGE_OBJECTION"),
    ("eic", "DECISION"),
    # desk-v3 C1（MAS_MORE_INTERACTION）：分版主編對總編刪稿申訴一次
    ("section_editor", "APPEAL"),
})

TOOLS = {
    "eic": frozenset({"read_pitches", "write_page_plan"}),
    "section_editor": frozenset({"read_section_candidates", "read_top_stories"}),
    "reporter": frozenset({"read_evidence", "write_story_version"}),
    "fact_checker": frozenset({"check_numbers", "check_entities", "check_relevance"}),
    "copy_editor": frozenset({"read_glossary", "check_length"}),
    "layout_editor": frozenset({"read_capacity", "read_page_plan"}),
}


class ToolDenied(PermissionError):
    pass


def call_tool(role: str, name: str, fn, *args, **kwargs):
    if name not in TOOLS.get(role, frozenset()):
        raise ToolDenied(f"{role} 不能使用 {name}")
    return fn(*args, **kwargs)


def challenge_count(session: Session, correlation_id: str | None) -> int:
    if not correlation_id:
        return 0
    return session.scalar(
        select(func.count()).select_from(AgentMessage).where(
            AgentMessage.correlation_id == correlation_id,
            AgentMessage.type == "CHALLENGE",
            AgentMessage.status != "rejected",
        )
    ) or 0


def post_message(
    session: Session,
    *,
    run_variant: str,
    edition_date: date,
    sender: str,
    recipient: str,
    type: str,
    now: datetime,
    story_id: int | None = None,
    target_version: int | None = None,
    payload: dict | None = None,
    correlation_id: str | None = None,
    llm_call_id: int | None = None,
    status: str | None = None,
) -> AgentMessage:
    """唯一的寫入口。不在白名單裡的訊息仍入表，status=rejected。

    同一個 correlation_id 的 CHALLENGE 超過 2 則時，改成 system HOLD（手冊 6.4 第 2 條）。
    一期超過 80 則 pending 訊息則標 expired，不再處理。
    """
    payload = dict(payload or {})
    if status is None:
        status = "pending" if (sender, type) in ALLOWED else "rejected"
    if type == "CHALLENGE" and status == "pending" and challenge_count(session, correlation_id) >= MAX_CHALLENGES:
        payload = {**payload, "reason": "同一個問題已來回 2 輪", "original_type": "CHALLENGE", "original_sender": sender}
        sender, type, status = "system", "HOLD", "pending"
    total = session.scalar(
        select(func.count()).select_from(AgentMessage).where(
            AgentMessage.edition_date == edition_date, AgentMessage.run_variant == run_variant
        )
    ) or 0
    if total >= MAX_MESSAGES and status == "pending":
        status = "expired"
    row = AgentMessage(
        run_variant=run_variant,
        edition_date=edition_date,
        story_id=story_id,
        sender_role=sender,
        recipient_role=recipient,
        type=type,
        target_version=target_version,
        payload=payload,
        correlation_id=correlation_id,
        status=status,
        created_at=now,
        llm_call_id=llm_call_id,
    )
    session.add(row)
    session.flush()
    if type == "HOLD" and status == "pending" and story_id is not None and latest_version(session, story_id) is not None:
        hold_story(session, story_id)
    if type == "CHALLENGE" and status == "pending" and story_id is not None:
        from ..store import set_status

        set_status(session, story_id, "challenged")
    return row


def claim_message(session: Session, message_id: int) -> bool:
    """UPDATE … WHERE status='pending'。搶不到就跳過（手冊 6.4 第 4 條）。"""
    result = session.execute(
        update(AgentMessage)
        .where(AgentMessage.id == message_id, AgentMessage.status == "pending")
        .values(status="claimed")
    )
    session.flush()
    return result.rowcount == 1


def mark_handled(session: Session, message_id: int) -> None:
    row = session.get(AgentMessage, message_id)
    if row is not None and row.status == "claimed":
        row.status = "handled"
        session.flush()


def recover_claimed(session: Session, edition_date: date, run_variant: str) -> int:
    """當機留下的 claimed 改回 pending，讓下一輪可以重跑。已寫進 llm_records 的請求由 request_hash 重播。"""
    result = session.execute(
        update(AgentMessage)
        .where(
            AgentMessage.edition_date == edition_date,
            AgentMessage.run_variant == run_variant,
            AgentMessage.status == "claimed",
        )
        .values(status="pending")
    )
    session.flush()
    return result.rowcount or 0


def correlation_id(kind: str, edition_date: date, story_id: int) -> str:
    return f"{kind}-{edition_date.strftime('%Y%m%d')}-{story_id:03d}"


# 編排器處理完就結案的訊息種類。HOLD（等真人）與 CHALLENGE（沒解決的異議）留著 pending。
SETTLED_TYPES = ("PITCH", "RELEASE", "PAGE_OBJECTION", "REVISION_DONE", "REBUT", "REQUEST_REVISION")


def settle_messages(session: Session, edition_date: date, run_variant: str) -> int:
    """一輪跑完，把編排器已經處理過的 pending 訊息標成 handled（手冊 6.3 的 status）。"""
    result = session.execute(
        update(AgentMessage)
        .where(
            AgentMessage.edition_date == edition_date,
            AgentMessage.run_variant == run_variant,
            AgentMessage.status == "pending",
            AgentMessage.type.in_(SETTLED_TYPES),
        )
        .values(status="handled")
    )
    session.flush()
    return result.rowcount or 0


_wall_clock: ContextVar[bool] = ContextVar("mas_wall_clock", default=False)


@contextmanager
def wall_clock(enabled: bool = True):
    """正式出刊（呼叫端沒指定 now）時，訊息與版本的時間用真實時間；重播、測試維持每則 +1 秒。"""
    token = _wall_clock.set(enabled)
    try:
        yield
    finally:
        _wall_clock.reset(token)


class Clock:
    def __init__(self, start: datetime) -> None:
        self.now = start

    def tick(self, seconds: int = 1) -> datetime:
        if _wall_clock.get():
            real = datetime.now(timezone.utc)
            if self.now.tzinfo is None:
                real = real.replace(tzinfo=None)
            # 至少比上一則晚 1 微秒，順序不會因為同一刻而亂掉
            self.now = max(self.now + timedelta(microseconds=1), real)
        else:
            self.now = self.now + timedelta(seconds=seconds)
        return self.now

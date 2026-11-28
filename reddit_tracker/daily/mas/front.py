"""頭版的分版提案、T1／T3 總編裁決、主稿縮稿與文稿編輯（P3-3 第 4 段，從 orchestrator.py 逐字搬出）。

`orchestrator` 以同名重新匯出，舊名稱相容。共用的模型呼叫與撰稿流程（`_ask`、`_revise`、
`apply_decision`…）與會被測試 patch 的 `build_evidence_from_ids` 仍在 orchestrator，這裡用 `orch.X`
在呼叫時查找（兩個模組互相引用，不能在 import 時取名稱）；`layout_limits` 和 desk_v3 一樣用
`layout.layout_limits` 查找，測試 patch `layout` 模組即可生效。
"""

from __future__ import annotations

import json
import logging
from dataclasses import replace
from typing import TYPE_CHECKING

from sqlalchemy import select

from ...collection.entities import load_lexicon
from ...config import get_settings
from ...llm.records import last_record_id
from ...models import PagePlan, Story
from ..store import MAS, add_page_plan, latest_version, write_story_version
from . import layout
from .checks import FRONT_CAPACITY, Pitch, _Checker, _decision_problems, _Decision, _Draft, _parse
from .desk_v3 import _open_section_pitches
from .prompts import (
    CHECKER_SCHEMA,
    COPY_SYSTEM,
    DRAFT_SCHEMA,
    EIC_SCHEMA,
    EIC_SYSTEM,
    PITCH_SCHEMA,
    PITCH_SYSTEM,
    REPORTER_SYSTEM,
)
from .protocol import claim_message, correlation_id, mark_handled, post_message

if TYPE_CHECKING:
    from .orchestrator import MasResult

logger = logging.getLogger("reddit_tracker.daily.mas.orchestrator")  # 沿用原本的 log 名稱

LEAD_MAX_CHARS = 300


def _section_pitches(session, edition_date, stories, evidence_of, client, calls: dict | None = None,
                     reasons_out: dict | None = None, layout_log: list[str] | None = None):
    rich = get_settings().mas_rich_context
    try:
        limits = layout.layout_limits()
    except ValueError as exc:
        logger.warning("MAS_OPEN_LAYOUT 設定不合法，改用固定名額：%s", exc)
        if layout_log is not None:
            layout_log.append(f"設定不合法，改用固定名額：{exc}")
        limits = None
    if limits is not None and limits.enabled:
        return _open_section_pitches(session, edition_date, stories, evidence_of, client, calls, limits, rich,
                                     reasons_out if reasons_out is not None else {},
                                     layout_log if layout_log is not None else [])
    pitches = orch._default_pitches(stories, evidence_of)
    top = sorted((s for s in stories if s.section in orch.SECTIONS), key=lambda s: -s.score)[:orch.GLOBAL_TOP_N]
    global_top = [{"story_id": s.id, "section": s.section, "score": s.score,
                   "title": (evidence_of.get(s.id) or [None])[0].title if evidence_of.get(s.id) else ""} for s in top]
    for section in orch.SECTIONS:
        own = [p for p in pitches if p.section == section]
        text = orch._ask(session, client, role="section_editor", story_id=None, edition_date=edition_date,
                    system=PITCH_SYSTEM, user=json.dumps({"section": section, "candidates": [
                        {**p.__dict__, "title": evidence_of[p.story_id][0].title,
                         **(orch.rich_fields(evidence_of.get(p.story_id)) if rich else {})} for p in own
                    ], "global_top10": global_top}, ensure_ascii=False), schema=PITCH_SCHEMA, temperature=0)
        if calls is not None:
            calls[section] = last_record_id()
        try:
            proposed = json.loads(text or "{}").get("pitches", [])
            by_id = {p["story_id"]: p for p in proposed if isinstance(p, dict) and "story_id" in p}
        except (ValueError, TypeError, AttributeError):
            by_id = {}
        for p in own:
            suggestion = by_id.get(p.story_id, {})
            p.angle = str(suggestion.get("angle") or p.angle)
            if suggestion.get("priority") in ("front", "section"):
                p.priority = suggestion["priority"]
    # Membership is fixed at 4 per section. Only report stories may reach front.
    kinds = {s.id: s.kind for s in stories}
    return [replace(p, priority="section") if kinds[p.story_id] != "report" else p for p in pitches]


def _conflicts(pitches: list[Pitch]) -> dict[int, list[Pitch]]:
    by: dict[int, list[Pitch]] = {}
    for pitch in pitches:
        by.setdefault(pitch.story_id, []).append(pitch)
    return {sid: group for sid, group in by.items() if len({p.section for p in group}) > 1}


def _story_card(session, story_id: int, hold_ids: set[int], evidence_of: dict | None = None) -> dict:
    """給總編看的稿件卡：標題、版別、種類、分數、是否 HOLD（不給全文）。

    MAS_RICH_CONTEXT 開啟且有證據包時，多帶 `rich_fields`（summary／outlets／outlet_count）。
    """
    story = session.get(Story, story_id)
    version = latest_version(session, story_id)
    card = {
        "story_id": story_id,
        "section": story.section if story else None,
        "kind": story.kind if story else None,
        "score": story.score if story else None,
        "headline": version.headline if version else "",
        "hold": story_id in hold_ids,
    }
    if evidence_of is not None and get_settings().mas_rich_context:
        card.update(orch.rich_fields(evidence_of.get(story_id)))
    return card


def _current_front(session, edition_date) -> list[int]:
    plan = session.scalar(select(PagePlan).where(
        PagePlan.edition_date == edition_date, PagePlan.run_variant == MAS
    ).order_by(PagePlan.plan_version.desc()))
    front = (plan.slots or {}).get("front") or {} if plan else {}
    return [i for i in [front.get("lead"), *(front.get("second") or []), *(front.get("briefs") or [])] if i]


def merge_t1_decision(previous_front: list[int], story_id: int, decision: _Decision) -> _Decision:
    """T1 只裁決被搶的那一篇：它在頭版的位置照總編的決定，頭版其他稿保持原順序（手冊 7.2）。"""
    others = [i for i in previous_front if i != story_id]
    if decision.lead == story_id:
        order = [story_id, *others]
    elif story_id in decision.second:
        order = others[:1] + [story_id] + others[1:]
    elif story_id in decision.briefs:
        order = others + [story_id]
    else:
        order = others  # 總編把它撤下頭版，只留在內版
    order = order[:FRONT_CAPACITY]
    return decision.model_copy(update={
        "lead": order[0] if order else None, "second": order[1:5], "briefs": order[5:],
    })


def _resolve_t1(session, *, edition_date, conflicts, client, clock, hold_ids, result: MasResult, pitches=None,
                evidence_of: dict | None = None) -> None:
    # 先留下提案當時的版面，決定之後才是下一版。
    flat = pitches or [pitch for group in conflicts.values() for pitch in group]
    proposal = add_page_plan(
        session, edition_date=edition_date, run_variant=MAS, slots=orch.slots_from_pitches(flat), now=clock.tick(),
    )
    result.page_plan_ids.append(proposal.id)
    for story_id, group in conflicts.items():
        previous_front = _current_front(session, edition_date)
        user = json.dumps(
            {
                "story": _story_card(session, story_id, hold_ids, evidence_of),
                "pitches": [p.__dict__ for p in group],
                "current_front": [_story_card(session, i, hold_ids, evidence_of) for i in previous_front],
            },
            ensure_ascii=False,
        )
        text = orch._ask(
            session, client, role="eic", story_id=story_id, edition_date=edition_date,
            system=EIC_SYSTEM + "\n兩個分版主編搶同一篇。只裁決這一篇：決定它歸哪一版當主稿、放頭版哪個位置"
                                "（lead／second／briefs，或都不放＝撤下頭版），另一版用 links 連結。"
                                "頭版其他稿不要動，程式會保留。每個決定在 reasons 寫理由。",
            user=user, schema=EIC_SCHEMA, temperature=0,
        )
        decision = _parse(text, _Decision)
        # 先驗總編的原始決定（同一篇佔兩個位置、HOLD 上頭版），合規則才併回原頭版；不讓合併把違規洗掉
        raw_problems = [
            problem for problem in _decision_problems(decision, hold_ids, min_front=0) if problem != "頭版沒有主稿"
        ] if decision is not None else []
        payload = decision.model_dump() if decision else {"error": "沒有可用的決定"}
        if decision and decision.reasons:
            payload["why"] = decision.reasons[0].get("why") or "同一事件不得有兩篇主稿"
        elif decision:
            payload["why"] = "同一事件不得有兩篇主稿"
        message = post_message(
            session, run_variant=MAS, edition_date=edition_date, sender="eic", recipient="section_editor",
            type="DECISION", now=clock.tick(), story_id=story_id, payload=payload, llm_call_id=last_record_id(),
        )
        if decision is None or raw_problems:
            message.status = "rejected"
            if raw_problems:
                message.payload = {**(message.payload or {}), "program_reason": "；".join(raw_problems)}
            result.rejected_decision_ids.append(message.id)
            session.flush()
            continue
        decision = merge_t1_decision(previous_front, story_id, decision)
        plan_id = orch.apply_decision(
            session, edition_date=edition_date, decision=decision, message=message, now=clock.tick(), hold_ids=hold_ids,
        )
        if plan_id is None:
            result.rejected_decision_ids.append(message.id)
        else:
            result.page_plan_ids.append(plan_id)


def _resolve_t3(session, *, edition_date, front, client, clock, hold_ids, result: MasResult,
                evidence_of: dict | None = None) -> None:
    if not session.scalar(select(PagePlan.id).where(PagePlan.edition_date == edition_date, PagePlan.run_variant == MAS)):
        plan = add_page_plan(session, edition_date=edition_date, run_variant=MAS,
                             slots=orch.slots_from_pitches(front), now=clock.tick())
        result.page_plan_ids.append(plan.id)
    post_message(
        session, run_variant=MAS, edition_date=edition_date, sender="layout_editor", recipient="eic",
        type="PAGE_OBJECTION", now=clock.tick(),
        payload={
            "page": "front", "problem": "OVER_CAPACITY" if len(front) > FRONT_CAPACITY else "LAYOUT_REVIEW",
            "detail": f"頭版 {FRONT_CAPACITY} 個位置，目前有 {len(front)} 則提案",
        },
    )
    eligible = [p for p in dict((p.story_id, p) for p in front).values() if p.story_id not in hold_ids]
    need = min(FRONT_CAPACITY, len(eligible))
    user = json.dumps({
        "capacity": FRONT_CAPACITY,
        "candidates": [{**_story_card(session, p.story_id, hold_ids, evidence_of), "pitched_by": p.section, "angle": p.angle}
                       for p in front],
    }, ensure_ascii=False)
    text = orch._ask(
        session, client, role="eic", story_id=None, edition_date=edition_date,
        system=EIC_SYSTEM + f"\n頭版提案超過容量。從 candidates 選剛好 {need} 則（hold=true 的不能選）："
                            "lead 1 則主稿、second 最多 4 則、其餘放 briefs。每則入選的在 reasons 寫為什麼上，"
                            "沒選的寫進 dropped 並寫為什麼不上。",
        user=user, schema=EIC_SCHEMA, temperature=0,
    )
    decision = _parse(text, _Decision)
    message = post_message(
        session, run_variant=MAS, edition_date=edition_date, sender="eic", recipient="layout_editor",
        type="DECISION", now=clock.tick(),
        payload=decision.model_dump() if decision else {"error": "沒有可用的決定"}, llm_call_id=last_record_id(),
    )
    if decision is None:
        message.status = "rejected"
        result.rejected_decision_ids.append(message.id)
        session.flush()
        return
    plan_id = orch.apply_decision(
        session, edition_date=edition_date, decision=decision, message=message, now=clock.tick(), hold_ids=hold_ids,
        min_front=need,
    )
    if plan_id is None:
        result.rejected_decision_ids.append(message.id)
    else:
        result.page_plan_ids.append(plan_id)


def _maybe_shorten_lead(session, *, edition_date, client, clock, degraded) -> None:
    from ...models import PagePlan

    plan = session.scalar(
        select(PagePlan).where(PagePlan.edition_date == edition_date, PagePlan.run_variant == MAS)
        .order_by(PagePlan.plan_version.desc())
    )
    if plan is None:
        return
    lead_id = (plan.slots.get("front") or {}).get("lead")
    if not lead_id:
        return
    version = latest_version(session, lead_id)
    if version is None or len(version.body) <= LEAD_MAX_CHARS:
        return
    message = post_message(
        session, run_variant=MAS, edition_date=edition_date, sender="layout_editor", recipient="reporter",
        type="REQUEST_REVISION", now=clock.tick(), story_id=lead_id, target_version=version.version,
        payload={"detail": f"主稿 {len(version.body)} 字，請縮到 {LEAD_MAX_CHARS} 字以內，不要刪關鍵事實"},
    )
    story = session.get(Story, lead_id)
    user = f"請把主稿縮到 {LEAD_MAX_CHARS} 字以內，action 填 REVISE。保留人名與數字。\n\n{version.body}"
    text = orch._ask(
        session, client, role="reporter", story_id=lead_id, edition_date=edition_date,
        system=REPORTER_SYSTEM, user=user, schema=DRAFT_SCHEMA, temperature=0.3,
    )
    shorten_call = last_record_id()
    draft = _parse(text, _Draft)
    body = draft.body if draft and draft.body else version.body[:LEAD_MAX_CHARS]
    if len(body) > LEAD_MAX_CHARS:
        body = body[:LEAD_MAX_CHARS]
    write_story_version(
        session, story_id=lead_id, run_variant=MAS, expected_latest=version.version,
        headline=version.headline, deck=version.deck or "", body=body, why_it_matters=version.why_it_matters or "",
        source_ids=list(version.source_ids or []), status=version.status, caused_by_message_id=message.id,
        now=clock.tick(), sender="agent",
    )
    post_message(
        session, run_variant=MAS, edition_date=edition_date, sender="reporter", recipient="layout_editor",
        type="REVISION_DONE", now=clock.tick(), story_id=lead_id,
        payload={"new_version": version.version + 1, "change": "縮短主稿"}, llm_call_id=shorten_call,
    )
    if story is not None and "copy_editor" not in degraded:
        _copy_confirm(session, edition_date=edition_date, story=story, before=version.body, clock=clock)


def _copy_confirm(session, *, edition_date, story, before, clock) -> None:
    version = latest_version(session, story.id)
    if version is None:
        return
    lexicon = load_lexicon()
    names = lexicon.glossary_names(before)
    missing = [name for name in names if name not in (version.body or "")]
    if missing:
        post_message(
            session, run_variant=MAS, edition_date=edition_date, sender="copy_editor", recipient="reporter",
            type="CHALLENGE", now=clock.tick(), story_id=story.id, target_version=version.version,
            payload={"problem": "DROPPED_FACT", "detail": f"縮稿後不見譯名：{'、'.join(missing)}"},
        )
        return
    post_message(
        session, run_variant=MAS, edition_date=edition_date, sender="copy_editor", recipient="eic",
        type="CHALLENGE", now=clock.tick(), story_id=story.id, target_version=version.version, status="handled",
        payload={"problem": "NONE", "detail": "縮稿沒有刪掉譯名"},
    )


def _copy_edit_front(session, *, edition_date, client, clock, degraded=None, context=None) -> None:
    """頭版稿各請文稿編輯看一次。模型沒有給判斷就不改稿。"""
    from ...models import PagePlan

    plan = session.scalar(
        select(PagePlan).where(PagePlan.edition_date == edition_date, PagePlan.run_variant == MAS)
        .order_by(PagePlan.plan_version.desc())
    )
    if plan is None or orch._quota_left(client) == 0:
        return
    front = plan.slots.get("front") or {}
    ids = [i for i in [front.get("lead"), *(front.get("second") or []), *(front.get("briefs") or [])] if i]
    for story_id in ids:
        if orch._quota_left(client) == 0:
            return
        version = latest_version(session, story_id)
        if version is None:
            continue
        text = orch._ask(
            session, client, role="copy_editor", story_id=story_id, edition_date=edition_date,
            system=COPY_SYSTEM, user=f"標題：{version.headline}\n正文：{version.body}",
            schema=CHECKER_SCHEMA, temperature=0,
        )
        copy_call = last_record_id()
        parsed = _parse(text, _Checker)
        if parsed is None or parsed.action != "CHALLENGE":
            continue
        corr = correlation_id("COPY", edition_date, story_id)
        message = post_message(
            session, run_variant=MAS, edition_date=edition_date, sender="copy_editor", recipient="reporter",
            type="CHALLENGE", now=clock.tick(), story_id=story_id, target_version=version.version,
            correlation_id=corr, payload={"problem": "COPY", "detail": parsed.detail,
                                          "required_action": parsed.required_action},
            llm_call_id=copy_call,
        )
        if not claim_message(session, message.id):
            continue  # 別的 worker 已經在處理（手冊 6.4 第 4 條）
        from ...seeds.news_sources import load_registry
        names = {s.id: s.name for s in load_registry().sources}
        evidence = orch._attach_fulltext(
            session, orch.build_evidence_from_ids(session, list(version.source_ids or []), names, context=context).items)
        if evidence:
            story = session.get(Story, story_id)
            orch._revise(session, edition_date=edition_date, story=story, evidence=evidence, removed=[],
                    version=version, client=client, clock=clock, corr=corr, challenge=message,
                    degraded=degraded if degraded is not None else [])
        else:
            post_message(session, run_variant=MAS, edition_date=edition_date, sender="system", recipient="human",
                         type="HOLD", now=clock.tick(), story_id=story_id, correlation_id=corr,
                         payload={"detail": "文稿異議缺乏可重驗證據，交人工"})
        mark_handled(session, message.id)


# orchestrator 在檔頭 import 本模組；放在最後，兩邊誰先被 import 都能載入（呼叫時才查 orch.X）。
from . import orchestrator as orch  # noqa: E402

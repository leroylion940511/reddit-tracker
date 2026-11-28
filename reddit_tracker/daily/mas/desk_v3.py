"""desk-v3 的開放版面、刪稿、申訴、版面審稿與總編退稿（P3-3 第 3 段，從 orchestrator.py 逐字搬出）。

這些步驟只在 MAS_OPEN_LAYOUT／MAS_MORE_INTERACTION 打開時跑；`orchestrator` 以同名重新匯出，舊名稱相容。
共用的模型呼叫與撰稿流程（`_ask`、`_check_and_maybe_revise`、`apply_decision`…）仍在 orchestrator，
這裡用 `orch.X` 在呼叫時查找（兩個模組互相引用，不能在 import 時取名稱）；`layout_limits` 用
`layout.layout_limits` 查找，測試 patch `layout` 模組即可生效。
"""

from __future__ import annotations

import json
from dataclasses import replace
from typing import TYPE_CHECKING

from pydantic import ValidationError
from sqlalchemy import select

from ...collection.entities import EntityContext
from ...config import get_settings
from ...llm.records import last_record_id
from ...models import PagePlan, Story
from ..store import MAS, latest_version, write_story_version
from . import layout
from .checks import FRONT_CAPACITY, Pitch, _decision_problems, _Decision, _Draft, _parse, evidence_has_injection
from .prompts import (
    APPEAL_RULING_SCHEMA,
    APPEAL_RULING_SUFFIX,
    APPEAL_SCHEMA,
    APPEAL_SYSTEM,
    DRAFT_SCHEMA,
    EIC_REQUEST_DETAIL_CHARS,
    EIC_REVIEW_SCHEMA,
    EIC_REVIEW_SUFFIX,
    EIC_REVISION_MAX,
    EIC_SYSTEM,
    OPEN_PITCH_SCHEMA,
    OPEN_PITCH_SYSTEM,
    PAGE_REVIEW_SCHEMA,
    PAGE_REVIEW_SYSTEM,
    PAGE_RULING_SCHEMA,
    PAGE_RULING_SUFFIX,
    REPORTER_SYSTEM,
    TRIM_SCHEMA,
    TRIM_SUFFIX,
)
from .protocol import correlation_id, post_message

if TYPE_CHECKING:
    from .orchestrator import MasResult


def guard_open_pitches(
    section: str, proposed, pool: list[Story], fallback: list[Pitch], limits, log: list[str],
) -> tuple[list[Pitch], dict[int, str]]:
    """把分版主編選的稿套上護欄，回傳 (pitches, {story_id: reason})。

    - `proposed` 不是 list（失敗、格式錯）→ 退回 `fallback`（select_articles 的結果）。
    - 只收候選池內、不重複的 story_id；front 只給 report；超過 section_max 截斷；
      少於 section_min 依候選池順序補足（理由記「程式補足下限」）。每個動作寫進 `log`。
    """
    if not isinstance(proposed, list):
        log.append(f"{section}：分版主編沒有可用的選稿，退回固定名額")
        return list(fallback), {}
    by_id = {s.id: s for s in pool}
    chosen: list[Pitch] = []
    reasons: dict[int, str] = {}
    for entry in proposed:
        sid = entry.get("story_id") if isinstance(entry, dict) else None
        if not isinstance(sid, int) or isinstance(sid, bool) or sid not in by_id:
            log.append(f"{section}：剔除不在候選池的選稿 {sid!r}")
            continue
        if sid in reasons:
            continue
        priority = "front" if entry.get("priority") == "front" and by_id[sid].kind == "report" else "section"
        chosen.append(Pitch(section=section, story_id=sid, angle=str(entry.get("angle") or section), priority=priority))
        reasons[sid] = str(entry.get("reason") or "")
    if len(chosen) > limits.section_max:
        dropped = [p.story_id for p in chosen[limits.section_max:]]
        log.append(f"{section}：選了 {len(chosen)} 篇，超過上限 {limits.section_max}，截掉 {dropped}")
        chosen = chosen[: limits.section_max]
        reasons = {p.story_id: reasons[p.story_id] for p in chosen}
    if len(chosen) < limits.section_min:
        for story in pool:
            if len(chosen) >= limits.section_min:
                break
            if story.id not in reasons:
                chosen.append(Pitch(section=section, story_id=story.id, angle=section, priority="section"))
                reasons[story.id] = "程式補足下限"
                log.append(f"{section}：少於下限 {limits.section_min}，補 {story.id}")
    return chosen, reasons


def _open_section_pitches(session, edition_date, stories, evidence_of, client, calls, limits, rich,
                          reasons_out: dict, log: list[str]) -> list[Pitch]:
    defaults = orch._default_pitches(stories, evidence_of)
    default_ids = {p.story_id for p in defaults}
    top = sorted((s for s in stories if s.section in orch.SECTIONS), key=lambda s: -s.score)[:orch.GLOBAL_TOP_N]
    global_top = [{"story_id": s.id, "section": s.section, "score": s.score,
                   "title": (evidence_of.get(s.id) or [None])[0].title if evidence_of.get(s.id) else ""} for s in top]
    pitches: list[Pitch] = []
    for section in orch.SECTIONS:
        pool = orch.section_pool(stories, evidence_of, section)
        fallback = [p for p in defaults if p.section == section]
        text = orch._ask(session, client, role="section_editor", story_id=None, edition_date=edition_date,
                    system=OPEN_PITCH_SYSTEM, user=json.dumps({
                        "section": section, "min": limits.section_min, "max": limits.section_max,
                        "candidates": [{"story_id": s.id, "kind": s.kind, "score": s.score,
                                        "title": evidence_of[s.id][0].title, "default": s.id in default_ids,
                                        **(orch.rich_fields(evidence_of.get(s.id)) if rich else {})} for s in pool],
                        "global_top10": global_top}, ensure_ascii=False),
                    schema=OPEN_PITCH_SCHEMA, temperature=0)
        if calls is not None:
            calls[section] = last_record_id()
        try:
            proposed = json.loads(text).get("pitches") if text else None
        except (ValueError, TypeError, AttributeError):
            proposed = None
        chosen, reasons = guard_open_pitches(section, proposed, pool, fallback, limits, log)
        pitches += chosen
        reasons_out.update(reasons)
    kinds = {s.id: s.kind for s in stories}
    return [replace(p, priority="section") if kinds[p.story_id] != "report" else p for p in pitches]


def program_trim(pitches: list[Pitch], scores: dict[int, float], limits, count: int,
                 keep_per_section: dict[str, int] | None = None) -> list[int]:
    """程式刪稿：分數最低的先刪（同分刪排在後面的），每版至少留 section_min 篇。回傳要刪的 story_id。"""
    left = dict(keep_per_section) if keep_per_section is not None else _section_counts(pitches)
    order = sorted(enumerate(pitches), key=lambda ip: (scores.get(ip[1].story_id, 0), -ip[0]))
    dropped: list[int] = []
    for _, pitch in order:
        if len(dropped) >= count:
            break
        if pitch.story_id in dropped or left.get(pitch.section, 0) <= limits.section_min:
            continue
        dropped.append(pitch.story_id)
        left[pitch.section] -= 1
    return dropped


def _section_counts(pitches: list[Pitch]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for pitch in pitches:
        counts[pitch.section] = counts.get(pitch.section, 0) + 1
    return counts


def guard_trim(proposed, pitches: list[Pitch], scores: dict[int, float], limits, count: int,
               log: list[str]) -> tuple[list[int], dict[int, str], str]:
    """把總編的刪稿名單套上護欄，回傳 (要刪的 story_id, {story_id: 理由}, by)。

    - 只收本期 pitches 內、不重複、刪了不會讓該版低於 section_min 的稿；多出 `count` 的忽略。
    - 不足 `count`（含 `proposed` 不是 list）由 `program_trim` 依分數補；by 是 eic／program／mixed。
    """
    by_id = {p.story_id: p for p in pitches}
    left = _section_counts(pitches)
    dropped: list[int] = []
    reasons: dict[int, str] = {}
    if isinstance(proposed, list):
        for entry in proposed:
            if len(dropped) >= count:
                log.append(f"總編刪稿超過 {count} 篇，多的不採用")
                break
            sid = entry.get("story_id") if isinstance(entry, dict) else None
            if not isinstance(sid, int) or isinstance(sid, bool) or sid not in by_id or sid in reasons:
                log.append(f"總編刪稿：剔除不在本期名單的 {sid!r}")
                continue
            section = by_id[sid].section
            if left[section] <= limits.section_min:
                log.append(f"總編刪稿：{sid} 會讓 {section} 少於下限 {limits.section_min}，不採用")
                continue
            left[section] -= 1
            dropped.append(sid)
            reasons[sid] = str(entry.get("why") or "")
    else:
        log.append("總編沒有可用的刪稿決定，改由程式依分數刪")
    by = "eic" if dropped else "program"
    if len(dropped) < count:
        rest = [p for p in pitches if p.story_id not in reasons]
        extra = program_trim(rest, scores, limits, count - len(dropped), keep_per_section=left)
        for sid in extra:
            reasons[sid] = "程式依分數刪"
        if extra and dropped:
            by = "mixed"
        if extra:
            log.append(f"程式依分數刪 {extra}")
        dropped += extra
    return dropped, reasons, by


def _trim_edition(session, *, edition_date, pitches: list[Pitch], stories: dict, evidence_of, reasons: dict,
                  client, clock, result: MasResult) -> list[Pitch]:
    """desk-v3 B3：開放版面時三版加總超過 MAS_EDITION_MAX，請總編一次決定刪哪幾篇。

    關閉、設定不合法或沒超過上限時原樣回傳（不呼叫模型、不發訊息）。決定（含理由與 by）寫進
    eic → section_editor 的 DECISION payload（action=TRIM）。
    """
    try:
        limits = layout.layout_limits()
    except ValueError:
        return pitches
    if not limits.enabled:
        return pitches
    total = len(dict.fromkeys(p.story_id for p in pitches))
    count = total - limits.edition_max
    if count <= 0:
        return pitches
    scores = {s.id: s.score for s in stories.values()}
    rich = get_settings().mas_rich_context
    cards = []
    for pitch in pitches:
        evidence = evidence_of.get(pitch.story_id) or []
        cards.append({
            "story_id": pitch.story_id, "section": pitch.section, "score": scores.get(pitch.story_id),
            "title": evidence[0].title if evidence else "", "angle": pitch.angle, "priority": pitch.priority,
            "reason": reasons.get(pitch.story_id, ""), **(orch.rich_fields(evidence) if rich else {}),
        })
    text = orch._ask(session, client, role="eic", story_id=None, edition_date=edition_date,
                system=EIC_SYSTEM + TRIM_SUFFIX, user=json.dumps({
                    "edition_max": limits.edition_max, "must_drop": count, "section_min": limits.section_min,
                    "stories": cards}, ensure_ascii=False),
                schema=TRIM_SCHEMA, temperature=0)
    call_id = last_record_id()
    try:
        proposed = json.loads(text).get("dropped") if text else None
    except (ValueError, TypeError, AttributeError):
        proposed = None
    dropped, why, by = guard_trim(proposed, pitches, scores, limits, count, result.layout_log)
    section_of = {p.story_id: p.section for p in pitches}
    trim_message = post_message(
        session, run_variant=MAS, edition_date=edition_date, sender="eic", recipient="section_editor",
        type="DECISION", now=clock.tick(), llm_call_id=call_id if by != "program" else None,
        payload={"action": "TRIM", "by": by, "edition_max": limits.edition_max, "before": total,
                 "after": total - len(dropped),
                 "dropped": [{"story_id": sid, "section": section_of[sid], "why": why[sid]} for sid in dropped],
                 "why": f"全期上限 {limits.edition_max} 篇，刪 {len(dropped)} 篇"},
    )
    result.layout_log.append(f"超過全期上限 {limits.edition_max}（{total} 篇），刪 {dropped}（{by}）")
    gone = set(dropped)
    if get_settings().mas_more_interaction and dropped:
        gone = _appeal_trim(session, edition_date=edition_date, pitches=pitches, cards=cards, gone=gone,
                            why=why, limits=limits, trim_message=trim_message, client=client, clock=clock,
                            result=result)
    return [p for p in pitches if p.story_id not in gone]

def appeal_section(pitches: list[Pitch], gone: set[int]) -> str | None:
    """被刪最多的版（同數取 SECTIONS 順序在前的）；沒有刪稿回 None。"""
    lost: dict[str, int] = {}
    for pitch in pitches:
        if pitch.story_id in gone:
            lost[pitch.section] = lost.get(pitch.section, 0) + 1
    if not lost:
        return None
    order = {s: i for i, s in enumerate(orch.SECTIONS)}
    return max(lost, key=lambda s: (lost[s], -order.get(s, 99)))


def guard_appeal_ruling(ruling, appealed: int, appeal_from: str, pitches: list[Pitch], gone: set[int],
                        limits) -> tuple[str, int | None, str | None]:
    """總編對申訴的裁決套護欄，回傳 (verdict, swap_out, 不採用的原因)。

    REVERSE 只在 swap_out 是目前保留、不是被申訴的稿，且換掉後該版不低於 section_min 時成立；
    否則一律當 UPHOLD（最保守：維持原刪稿名單）。
    """
    if not isinstance(ruling, dict) or ruling.get("verdict") not in ("UPHOLD", "REVERSE"):
        return "UPHOLD", None, "總編沒有可用的裁決，維持原判"
    if ruling["verdict"] == "UPHOLD":
        return "UPHOLD", None, None
    swap = ruling.get("swap_out")
    kept = {p.story_id: p.section for p in pitches if p.story_id not in gone}
    if not isinstance(swap, int) or isinstance(swap, bool) or swap not in kept or swap == appealed:
        return "UPHOLD", None, f"改判的 swap_out {swap!r} 不是目前保留的稿，維持原判"
    section = kept[swap]
    left = sum(1 for sid, sec in kept.items() if sec == section) + (1 if section == appeal_from else 0)
    if left - 1 < limits.section_min:
        return "UPHOLD", None, f"改刪 {swap} 會讓 {section} 少於下限 {limits.section_min}，維持原判"
    return "REVERSE", swap, None


def _appeal_trim(session, *, edition_date, pitches: list[Pitch], cards: list[dict], gone: set[int], why: dict,
                 limits, trim_message, client, clock, result: MasResult) -> set[int]:
    """desk-v3 C1：被刪最多的分版主編申訴一次（APPEAL），總編回 DECISION（UPHOLD／REVERSE）。最多 1 輪。

    分版主編不申訴或回應無效 → 不發訊息。回傳新的刪稿集合。
    """
    section = appeal_section(pitches, gone)
    if section is None:
        return gone
    by_id = {c["story_id"]: c for c in cards}
    mine_dropped = [{**by_id[p.story_id], "eic_why": why.get(p.story_id, "")}
                    for p in pitches if p.section == section and p.story_id in gone]
    mine_kept = [by_id[p.story_id] for p in pitches if p.section == section and p.story_id not in gone]
    text = orch._ask(session, client, role="section_editor", story_id=None, edition_date=edition_date,
                system=APPEAL_SYSTEM, user=json.dumps({"section": section, "dropped": mine_dropped,
                                                       "kept": mine_kept}, ensure_ascii=False),
                schema=APPEAL_SCHEMA, temperature=0)
    appeal_call = last_record_id()
    try:
        appeal = json.loads(text) if text else None
    except (ValueError, TypeError):
        appeal = None
    dropped_ids = {d["story_id"] for d in mine_dropped}
    sid = appeal.get("story_id") if isinstance(appeal, dict) else None
    if not (isinstance(appeal, dict) and appeal.get("appeal") is True and isinstance(sid, int)
            and not isinstance(sid, bool) and sid in dropped_ids):
        result.layout_log.append(f"{section}：分版主編不申訴（或申訴無效）")
        return gone
    appeal_message = post_message(
        session, run_variant=MAS, edition_date=edition_date, sender="section_editor", recipient="eic",
        type="APPEAL", now=clock.tick(), story_id=sid, llm_call_id=appeal_call,
        payload={"section": section, "why": str(appeal.get("why") or ""), "trim_message_id": trim_message.id},
    )
    kept_all = [by_id[p.story_id] for p in pitches if p.story_id not in gone]
    text = orch._ask(session, client, role="eic", story_id=sid, edition_date=edition_date,
                system=EIC_SYSTEM + APPEAL_RULING_SUFFIX, user=json.dumps({
                    "section_min": limits.section_min,
                    "appeal": {"story": by_id[sid], "why": str(appeal.get("why") or ""), "eic_why": why.get(sid, "")},
                    "kept": kept_all}, ensure_ascii=False),
                schema=APPEAL_RULING_SCHEMA, temperature=0)
    ruling_call = last_record_id()
    try:
        ruling = json.loads(text) if text else None
    except (ValueError, TypeError):
        ruling = None
    verdict, swap, problem = guard_appeal_ruling(ruling, sid, section, pitches, gone, limits)
    payload = {"action": "APPEAL_RULING", "verdict": verdict, "story_id": sid, "swap_out": swap,
               "appeal_message_id": appeal_message.id,
               "why": str((ruling or {}).get("why") or "") if isinstance(ruling, dict) else ""}
    if problem:
        payload["program_reason"] = problem
        result.layout_log.append(f"申訴 {sid}：{problem}")
    post_message(session, run_variant=MAS, edition_date=edition_date, sender="eic", recipient="section_editor",
                 type="DECISION", now=clock.tick(), story_id=sid, llm_call_id=ruling_call, payload=payload)
    if verdict == "REVERSE":
        result.layout_log.append(f"申訴 {sid} 改判：保留 {sid}，改刪 {swap}")
        return (gone - {sid}) | {swap}
    result.layout_log.append(f"申訴 {sid} 維持原判")
    return gone


def _front_ids(slots: dict) -> list[int]:
    front = (slots or {}).get("front") or {}
    return [i for i in [front.get("lead"), *(front.get("second") or []), *(front.get("briefs") or [])] if i]


def guard_page_proposal(review, plan_slots: dict, eligible: set[int], hold_ids: set[int]
                        ) -> tuple[_Decision | None, str | None]:
    """版面編輯的頭版提案套護欄，回傳 (提案, 不採用的原因)。

    action 不是 OBJECT → (None, None)：沒有異議。OBJECT 時提案要符合頭版規則（`_decision_problems`：
    有主稿、不重複、不超過容量、沒有 HOLD）、只用 eligible 裡的稿、篇數不比現在少、跟現在不一樣，
    且不能把在兩個版都有位置（T1 連結）的稿撤下頭版；不合規則回 (None, 原因)。
    """
    if not isinstance(review, dict) or review.get("action") != "OBJECT":
        return None, None
    try:
        proposal = _Decision(lead=review.get("lead"), second=review.get("second") or [],
                             briefs=review.get("briefs") or [])
    except ValidationError:
        return None, "提案格式不對"
    current = _front_ids(plan_slots)
    chosen = [i for i in [proposal.lead, *proposal.second, *proposal.briefs] if i is not None]
    problems = _decision_problems(proposal, hold_ids, min_front=len(current))
    if any(i not in eligible for i in chosen):
        problems.append("頭版只能用本期可上頭版的稿")
    if len(proposal.second) > 4:
        problems.append("second 最多 4 則")
    if (proposal.lead, proposal.second, proposal.briefs) == (
            (plan_slots.get("front") or {}).get("lead"), list((plan_slots.get("front") or {}).get("second") or []),
            list((plan_slots.get("front") or {}).get("briefs") or [])):
        problems.append("提案和現在的頭版一樣")
    placed: dict[int, int] = {}
    for entries in (plan_slots.get("sections") or {}).values():
        for slot in entries:
            placed[slot["story_id"]] = placed.get(slot["story_id"], 0) + 1
    if any(placed.get(i, 0) > 1 and i not in chosen for i in current):
        problems.append("兩個版都有位置的稿不能撤下頭版")
    if problems:
        return None, "；".join(dict.fromkeys(problems))
    return proposal, None


def _page_review(session, *, edition_date, client, clock, hold_ids: set[int], evidence_of: dict,
                 result: MasResult) -> None:
    """desk-v3 C2：總編排定頭版後版面編輯審一次（PAGE_OBJECTION），總編回 DECISION（ACCEPT／REJECT）。最多 1 輪。

    版面編輯說 OK 或沒有回應 → 不發訊息。提案不合頭版規則 → 程式代回 REJECT（by=program，不問總編）。
    總編沒有可用的裁決 → 當 REJECT。ACCEPT 時用 `orch.apply_decision` 寫下一版 page plan（仍套頭版規則）。
    """
    plan = session.scalar(select(PagePlan).where(
        PagePlan.edition_date == edition_date, PagePlan.run_variant == MAS
    ).order_by(PagePlan.plan_version.desc()))
    if plan is None:
        return
    slots = plan.slots or {}
    current = _front_ids(slots)
    position = {}
    front = slots.get("front") or {}
    for sid in current:
        position[sid] = "lead" if sid == front.get("lead") else ("second" if sid in (front.get("second") or []) else "briefs")
    others: list[int] = []
    for entries in (slots.get("sections") or {}).values():
        for slot in entries:
            sid = slot["story_id"]
            story = session.get(Story, sid)
            if (sid in current or sid in others or sid in hold_ids or story is None or story.kind != "report"
                    or evidence_has_injection(evidence_of.get(sid) or [])):
                continue
            others.append(sid)
    count = {section: len(entries) for section, entries in (slots.get("sections") or {}).items()}

    def cards(ids, with_slot):
        return [{**orch._story_card(session, i, hold_ids, evidence_of), **({"slot": position[i]} if with_slot else {})}
                for i in ids]

    text = orch._ask(session, client, role="layout_editor", story_id=None, edition_date=edition_date,
                system=PAGE_REVIEW_SYSTEM, user=json.dumps({
                    "capacity": FRONT_CAPACITY, "front": cards(current, True), "others": cards(others, False),
                    "section_counts": count}, ensure_ascii=False),
                schema=PAGE_REVIEW_SCHEMA, temperature=0)
    review_call = last_record_id()
    try:
        review = json.loads(text) if text else None
    except (ValueError, TypeError):
        review = None
    if not (isinstance(review, dict) and review.get("action") == "OBJECT"):
        result.layout_log.append("版面編輯審頭版：沒有異議" if isinstance(review, dict) else "版面編輯審頭版：沒有可用的回應")
        return
    proposal, problem = guard_page_proposal(review, slots, set(current) | set(others), hold_ids)
    proposed = {"lead": review.get("lead"), "second": review.get("second") or [], "briefs": review.get("briefs") or []}
    objection = post_message(
        session, run_variant=MAS, edition_date=edition_date, sender="layout_editor", recipient="eic",
        type="PAGE_OBJECTION", now=clock.tick(), llm_call_id=review_call,
        payload={"page": "front", "problem": str(review.get("problem") or ""), "detail": str(review.get("detail") or ""),
                 "proposal": proposed, "plan_id": plan.id},
    )
    base = {"action": "PAGE_RULING", "objection_message_id": objection.id, "proposal": proposed}
    if proposal is None:
        payload = {**base, "verdict": "REJECT", "by": "program", "why": "提案不合頭版規則",
                   "program_reason": problem or "提案格式不對"}
        message = post_message(session, run_variant=MAS, edition_date=edition_date, sender="eic",
                               recipient="layout_editor", type="DECISION", now=clock.tick(), payload=payload)
        message.status = "handled"
        session.flush()
        result.layout_log.append(f"版面異議：提案不合規則，程式駁回（{payload['program_reason']}）")
        return
    proposed_ids = [i for i in [proposal.lead, *proposal.second, *proposal.briefs] if i is not None]
    pos = {proposal.lead: "lead", **{i: "second" for i in proposal.second}, **{i: "briefs" for i in proposal.briefs}}
    text = orch._ask(session, client, role="eic", story_id=None, edition_date=edition_date,
                system=EIC_SYSTEM + PAGE_RULING_SUFFIX, user=json.dumps({
                    "objection": {"problem": str(review.get("problem") or ""), "detail": str(review.get("detail") or "")},
                    "current_front": cards(current, True),
                    "proposed_front": [{**orch._story_card(session, i, hold_ids, evidence_of), "slot": pos[i]}
                                       for i in proposed_ids]}, ensure_ascii=False),
                schema=PAGE_RULING_SCHEMA, temperature=0)
    ruling_call = last_record_id()
    try:
        ruling = json.loads(text) if text else None
    except (ValueError, TypeError):
        ruling = None
    verdict = ruling.get("verdict") if isinstance(ruling, dict) else None
    payload = {**base, "verdict": verdict if verdict in ("ACCEPT", "REJECT") else "REJECT",
               "by": "eic" if verdict in ("ACCEPT", "REJECT") else "program",
               "why": str(ruling.get("why") or "") if isinstance(ruling, dict) else ""}
    if verdict not in ("ACCEPT", "REJECT"):
        payload["program_reason"] = "總編沒有可用的裁決，維持原版面"
    message = post_message(session, run_variant=MAS, edition_date=edition_date, sender="eic",
                           recipient="layout_editor", type="DECISION", now=clock.tick(), payload=payload,
                           llm_call_id=ruling_call if payload["by"] == "eic" else None)
    if payload["verdict"] == "REJECT":
        message.status = "handled"
        session.flush()
        result.layout_log.append("版面異議：總編駁回，維持原頭版")
        return
    plan_id = orch.apply_decision(session, edition_date=edition_date, decision=proposal, message=message,
                             now=clock.tick(), hold_ids=hold_ids, min_front=len(current))
    if plan_id is None:
        result.rejected_decision_ids.append(message.id)
        result.layout_log.append("版面異議：總編接受但不合頭版規則，維持原頭版")
    else:
        result.page_plan_ids.append(plan_id)
        result.layout_log.append(f"版面異議：總編接受，頭版改為 {proposed_ids}")


def guard_eic_requests(proposed, reviewable: set[int], limit: int = EIC_REVISION_MAX) -> list[tuple[int, str]]:
    """總編退稿名單套護欄：只收 reviewable 裡的、不重複、detail 非空（截到 EIC_REQUEST_DETAIL_CHARS），最多 limit 篇。"""
    out: list[tuple[int, str]] = []
    if not isinstance(proposed, list):
        return out
    for entry in proposed:
        if not isinstance(entry, dict):
            continue
        sid, detail = entry.get("story_id"), entry.get("detail")
        if (not isinstance(sid, int) or isinstance(sid, bool) or sid not in reviewable
                or any(sid == s for s, _ in out) or not isinstance(detail, str) or not detail.strip()):
            continue
        out.append((sid, detail.strip()[:EIC_REQUEST_DETAIL_CHARS]))
        if len(out) >= limit:
            break
    return out


def _eic_revisions(session, *, edition_date, client, clock, hold_ids: set[int], evidence_of: dict,
                   result: MasResult, day_context: EntityContext | None = None) -> None:
    """desk-v3 C3：總編看頭版稿，最多對 EIC_REVISION_MAX 篇發 REQUEST_REVISION；記者回 REVISION_DONE（或 REBUT），
    改過的稿照原流程（`orch._check_and_maybe_revise`）重驗。只審 status=checked 的頭版稿。

    記者降級或額度用完時整段跳過；總編回應無效＝不退稿。修稿後重驗變 HOLD 的稿留在版面上，
    跟其他 HOLD 稿一樣由發佈時的人工核可擋下（不在這裡改 page plan）。
    """
    if "reporter" in result.degraded or orch._quota_left(client) == 0:
        return
    plan = session.scalar(select(PagePlan).where(
        PagePlan.edition_date == edition_date, PagePlan.run_variant == MAS
    ).order_by(PagePlan.plan_version.desc()))
    if plan is None:
        return
    front_ids = _front_ids(plan.slots or {})
    cards, versions = [], {}
    for sid in front_ids:
        version = latest_version(session, sid)
        if sid in hold_ids or version is None or version.status != "checked":
            continue
        versions[sid] = version
        cards.append({"story_id": sid, "headline": version.headline, "deck": version.deck or "",
                      "summary": orch.rich_fields(evidence_of.get(sid))["summary"]})
    if not cards:
        return
    text = orch._ask(session, client, role="eic", story_id=None, edition_date=edition_date,
                system=EIC_SYSTEM + EIC_REVIEW_SUFFIX,
                user=json.dumps({"max": EIC_REVISION_MAX, "front": cards}, ensure_ascii=False),
                schema=EIC_REVIEW_SCHEMA, temperature=0)
    eic_call = last_record_id()
    try:
        proposed = json.loads(text).get("requests") if text else None
    except (ValueError, TypeError, AttributeError):
        proposed = None
    requests = guard_eic_requests(proposed, set(versions))
    if not requests:
        result.layout_log.append("總編審頭版稿：不退稿")
        return
    per_source = get_settings().fact_checker_per_source
    event_classes = get_settings().fact_checker_event_classes
    for sid, detail in requests:
        story = session.get(Story, sid)
        version = versions[sid]
        evidence = evidence_of.get(sid) or []
        corr = correlation_id("ER", edition_date, sid)
        request = post_message(
            session, run_variant=MAS, edition_date=edition_date, sender="eic", recipient="reporter",
            type="REQUEST_REVISION", now=clock.tick(), story_id=sid, target_version=version.version,
            correlation_id=corr, llm_call_id=eic_call, payload={"detail": detail, "by": "eic"},
        )
        if orch._quota_left(client) == 0:
            result.layout_log.append(f"總編退稿 {sid}：額度用完，記者沒改")
            continue
        user = (f"總編 REQUEST_REVISION：{detail}\n請依要求改稿，action 填 REVISE；只能用證據裡的事實。"
                f"不同意就 action 填 REBUT 並在 reason 寫理由。\n\n現稿標題：{version.headline}\n"
                f"現稿導言：{version.deck or ''}\n現稿正文：{version.body}\n\n{orch._evidence_block(evidence)}")
        text = orch._ask(session, client, role="reporter", story_id=sid, edition_date=edition_date,
                    system=REPORTER_SYSTEM, user=user, schema=DRAFT_SCHEMA, temperature=0.3)
        reporter_call = last_record_id()
        draft = _parse(text, _Draft)
        if draft is not None and draft.action == "REBUT":
            post_message(session, run_variant=MAS, edition_date=edition_date, sender="reporter", recipient="eic",
                         type="REBUT", now=clock.tick(), story_id=sid, correlation_id=corr,
                         payload={"reason": draft.reason, "target_version": version.version},
                         llm_call_id=reporter_call)
            result.layout_log.append(f"總編退稿 {sid}：記者反駁，維持原稿")
            continue
        if draft is None or not draft.body or not draft.headline:
            result.layout_log.append(f"總編退稿 {sid}：記者沒有可用的修改，維持原稿")
            continue
        new = write_story_version(
            session, story_id=sid, run_variant=MAS, expected_latest=version.version, headline=draft.headline,
            deck=draft.deck, body=draft.body, why_it_matters=draft.why_it_matters or version.why_it_matters or "",
            source_ids=list(version.source_ids or []), status="draft", caused_by_message_id=request.id,
            now=clock.tick(), sender="agent",
        )
        post_message(session, run_variant=MAS, edition_date=edition_date, sender="reporter", recipient="eic",
                     type="REVISION_DONE", now=clock.tick(), story_id=sid, correlation_id=corr,
                     payload={"new_version": new.version, "change": detail}, llm_call_id=reporter_call)
        final = orch._check_and_maybe_revise(
            session, edition_date=edition_date, story=story, evidence=evidence, version=new, client=client,
            clock=clock, corr=corr, degraded=result.degraded, per_source=per_source, day_context=day_context,
            event_classes=event_classes,
        )
        if final.status == "hold":
            hold_ids.add(sid)
        result.layout_log.append(f"總編退稿 {sid}：記者改到 v{new.version}，重驗後 {final.status}")


# orchestrator 在檔頭 import 本模組；放在最後，兩邊誰先被 import 都能載入（呼叫時才查 orch.X）。
from . import orchestrator as orch  # noqa: E402

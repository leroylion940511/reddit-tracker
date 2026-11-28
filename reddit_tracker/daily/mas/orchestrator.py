"""編輯室一轮：分版提案、記者、查核、必要時才開 T1／T3。程式做決定，模型只做小判斷。"""

from __future__ import annotations

import json
import logging
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...collection.clustering import domain_of
from ...config import get_settings
from ...collection.entities import EntityContext, load_lexicon
from ...llm.deadline import deadline_reached
from ...llm.quota import QuotaExhausted
from ...llm.records import bind_log_session, complete_logged, last_record_id, llm_log_meta, reset_last_record
from ...models import AgentMessage, PagePlan, SourceItem, Story, StoryVersion
from ..evidence import EvidenceItem, EvidencePack, build_evidence_from_ids, title_context, with_fulltext
from ..noise import story_noise
from ..scoring import DESK_POOL_PER_SECTION, SECTION_KINDS, SECTION_QUOTAS, ScoredCluster, select_articles
from ..store import MAS, add_page_plan, add_story, hold_story, latest_version, write_story_version
from ..writer import finalize_story, template_story, unsupported_numbers
from .layout import layout_limits  # noqa: F401  重新匯出（測試會 patch 這個名稱）
from .protocol import (
    Clock,
    call_tool,
    claim_message,
    correlation_id,
    mark_handled,
    post_message,
    recover_claimed,
    settle_messages,
)
from .checks import (  # noqa: F401  重新匯出，舊名稱相容
    CHECKER_MIN_ZH_FRAGMENTS,
    FRONT_CAPACITY,
    INJECTION_MARKERS,
    Pitch,
    _Checker,
    _Decision,
    _Draft,
    _decision_problems,
    _evidence_text,
    _has_marker,
    _parse,
    _percent_values,
    _sid,
    _usable_fulltext,
    checker_says_same_event,
    checker_source_verdicts,
    evidence_has_injection,
    guard_pitches,
    irrelevant_sources,
)
from .prompts import (  # noqa: F401  重新匯出，舊名稱相容
    APPEAL_RULING_SCHEMA,
    APPEAL_RULING_SUFFIX,
    APPEAL_SCHEMA,
    APPEAL_SYSTEM,
    CHECKER_EVENT_CLASS_SCHEMA,
    CHECKER_EVENT_CLASS_SUFFIX,
    CHECKER_PER_SOURCE_SCHEMA,
    CHECKER_PER_SOURCE_SUFFIX,
    CHECKER_RELEVANCE_SUFFIX,
    CHECKER_SCHEMA,
    CHECKER_SYSTEM,
    COPY_SYSTEM,
    DRAFT_SCHEMA,
    EIC_REQUEST_DETAIL_CHARS,
    EIC_REVIEW_SCHEMA,
    EIC_REVIEW_SUFFIX,
    EIC_REVISION_MAX,
    EIC_SCHEMA,
    EIC_SYSTEM,
    EVENT_RELATIONS,
    EVENT_RELATION_KEEP,
    OPEN_PITCH_SCHEMA,
    OPEN_PITCH_SYSTEM,
    PAGE_REVIEW_SCHEMA,
    PAGE_REVIEW_SYSTEM,
    PAGE_RULING_SCHEMA,
    PAGE_RULING_SUFFIX,
    PITCH_SCHEMA,
    PITCH_SYSTEM,
    REPORTER_SYSTEM,
    TRIM_SCHEMA,
    TRIM_SUFFIX,
)
from .desk_v3 import (  # noqa: F401  重新匯出，舊名稱相容
    appeal_section,
    _appeal_trim,
    _eic_revisions,
    _front_ids,
    guard_appeal_ruling,
    guard_eic_requests,
    guard_open_pitches,
    guard_page_proposal,
    guard_trim,
    _open_section_pitches,
    _page_review,
    program_trim,
    _section_counts,
    _trim_edition,
)
from .front import (  # noqa: F401  重新匯出，舊名稱相容
    LEAD_MAX_CHARS,
    _conflicts,
    _copy_confirm,
    _copy_edit_front,
    _current_front,
    _maybe_shorten_lead,
    _resolve_t1,
    _resolve_t3,
    _section_pitches,
    _story_card,
    merge_t1_decision,
)

logger = logging.getLogger(__name__)

# desk-v3 A1（MAS_RICH_CONTEXT）：主編／總編看到的 S1 摘要長度上限
RICH_SUMMARY_CHARS = 200
SECTIONS = tuple(SECTION_QUOTAS)
# MAS_FULL_EVIDENCE：來源的實際文章網域怎麼算（article_domains）
ARTICLE_DOMAIN_WINDOW = timedelta(days=7)
ARTICLE_DOMAIN_MIN_ITEMS = 5
ARTICLE_DOMAIN_MIN_SHARE = 0.2


# 查核員開關（實驗二，手冊 8.2）。線上只用 full。
CHECKER_MODES = ("full", "program", "off")


@dataclass
class MasResult:
    degraded: list[str] = field(default_factory=list)
    injection_log: list[str] = field(default_factory=list)
    page_plan_ids: list[int] = field(default_factory=list)
    rejected_decision_ids: list[int] = field(default_factory=list)
    # desk-v3 B2（MAS_OPEN_LAYOUT）：程式對分版主編選稿套的護欄紀錄（截斷、剔除、補足、退回）
    layout_log: list[str] = field(default_factory=list)
    # MAS_NOISE_CHECK：因模型雜訊被 HOLD 的稿（story_id → 命中的欄位與片段）
    noise_log: dict[int, dict[str, list[str]]] = field(default_factory=dict)


def registry_domains(registry) -> frozenset[str]:
    domains = set()
    for source in registry.sources:
        if source.url.startswith("http"):
            domains.add(domain_of(source.url))
    return frozenset(domains)


def article_domains(session: Session, registry, now: datetime) -> frozenset[str]:
    """MAS_FULL_EVIDENCE：登錄表來源近 7 天實際文章的網域（feed 掛 feedburner、RSSHub 的來源才認得出來）。

    單一來源至少 `ARTICLE_DOMAIN_MIN_ITEMS` 篇，且該網域占這個來源 `ARTICLE_DOMAIN_MIN_SHARE` 以上才算；
    Hacker News 這類會連到任意網域的聚合站，長尾網域因此進不來（假來源防護不放鬆）。只算當時已收到的素材。
    """
    ids = {s.id for s in registry.sources} - registry.disabled_source_ids()
    counts: dict[str, Counter] = {}
    rows = session.execute(
        select(SourceItem.source_id, SourceItem.canonical_url).where(
            SourceItem.source_id.in_(sorted(ids)),
            SourceItem.first_seen_at >= now - ARTICLE_DOMAIN_WINDOW,
            SourceItem.first_seen_at <= now,
        )
    )
    for source_id, url in rows:
        counts.setdefault(source_id, Counter())[domain_of(url)] += 1
    found = set()
    for counter in counts.values():
        total = sum(counter.values())
        if total >= ARTICLE_DOMAIN_MIN_ITEMS:
            found |= {d for d, n in counter.items() if n / total >= ARTICLE_DOMAIN_MIN_SHARE}
    return frozenset(found)


def _attach_fulltext(session: Session, items: list[EvidenceItem]) -> list[EvidenceItem]:
    """desk-v3 D3：`MAS_REPORTER_FULLTEXT` 開啟時換上 item_fulltext 的全文；關閉時原樣回傳。"""
    settings = get_settings()
    if not settings.mas_reporter_fulltext or not items:
        return items
    from ...collection.fulltext import fulltext_of

    texts = fulltext_of(session, [item.item_id for item in items if item.item_id is not None])
    return with_fulltext(items, texts, settings.mas_reporter_fulltext_chars)


def _body_line(item: EvidenceItem) -> str:
    full = _usable_fulltext(item)
    return f"全文：{full}" if full else f"摘要：{item.summary}"


def _evidence_block(evidence: list[EvidenceItem]) -> str:
    blocks = []
    for index, item in enumerate(evidence, start=1):
        blocks.append(
            f"<<<S{index}>>>\n媒體：{item.display_name}\n標題：{item.title}\n{_body_line(item)}\n<<</S{index}>>>"
        )
    return "\n\n".join(blocks)


def _quota_left(client) -> int | None:
    """剩幾格額度；過了準備截止（llm/deadline.py）也當成 0，照額度用完的順序降級。"""
    if deadline_reached():
        return 0
    guard = getattr(client, "guard", None)
    model = getattr(client, "model", None)
    if guard is None or model is None:
        return None
    return guard.daily_limit - guard.used(model)


def _degrade(degraded, role):
    for item in ("copy_editor", "fact_checker", "reporter"):
        if item not in degraded:
            degraded.append(item)
        if item == role:
            break


def _ask(session, client, *, role, story_id, edition_date, system, user, schema, temperature) -> str | None:
    """回傳模型文字。額度用完或呼叫失敗回 None，由呼叫端降級。

    這次呼叫寫的 llm_records.id 用 `last_record_id()` 取（沒呼叫就是 None），給訊息的 llm_call_id。
    """
    reset_last_record()
    if _quota_left(client) == 0:
        return None
    kwargs = dict(
        system=system, messages=[{"role": "user", "content": user}], max_output_tokens=2000,
        temperature=temperature, json_mode=True, json_schema=schema,
    )
    try:
        with llm_log_meta(role=role, run_variant=MAS, edition_date=edition_date, story_id=story_id, purpose=role):
            return complete_logged(client, session, **kwargs)
    except QuotaExhausted:
        return None
    except Exception as exc:  # noqa: BLE001 — 角色呼叫失敗就降級，不讓整期停住
        logger.warning("%s call failed: %s", role, exc)
        return None


def cleared_item_ids(session: Session, story_id: int) -> set[int]:
    """查核員判定同一事件而保留的可疑來源（素材 id）；修稿後重驗不再把它們當無關來源。"""
    rows = session.scalars(select(AgentMessage.payload).where(
        AgentMessage.story_id == story_id, AgentMessage.sender_role.in_(("fact_checker", "system")),
    ))
    return {int(i) for payload in rows for i in (payload or {}).get("cleared_item_ids") or []}


def _cleared_payload(cleared: list[tuple[int, EvidenceItem]]) -> dict:
    return {
        "cleared_sids": [index for index, _ in cleared],
        "cleared_item_ids": [item.item_id for _, item in cleared if item.item_id is not None],
    }


def _draft_from_template(evidence: list[EvidenceItem], kind: str):
    story = finalize_story(template_story(evidence, kind), evidence, kind)
    return story.headline, story.deck, story.body, story.why_it_matters


def review_one(
    session: Session,
    *,
    edition_date: date,
    story: Story,
    evidence: list[EvidenceItem],
    client,
    now: datetime,
    degraded: list[str] | None = None,
    per_source: bool | None = None,
    checker_mode: str = "full",
    draft: tuple[str, str, str, str] | None = None,
    day_context: EntityContext | None = None,
    event_classes: bool | None = None,
) -> StoryVersion:
    """記者寫 v1，程式查核；有問題才 CHALLENGE，通過則 checked。

    `per_source` 沒給就看 `FACT_CHECKER_PER_SOURCE`（預設 false＝舊提示詞與舊 schema）。
    `checker_mode`、`draft` 只給實驗二用（手冊 8.2）：線上一律是預設值，請求與行為不變。
    - `checker_mode`：`full`＝程式工具＋查核員 LLM；`program`＝只開程式工具；`off`＝查核員全關（數字檢查照開）。
    - `draft`：已存檔的 v1（headline, deck, body, why_it_matters），有給就不呼叫記者。
    `day_context`：當天素材的 EntityContext，給了查核員程式點名才比中文片段（`FACT_CHECKER_ZH_FRAGMENTS`）。
    `event_classes` 沒給就看 `FACT_CHECKER_EVENT_CLASSES`（預設 false）；true 時查核員對點名來源回事件四分類，
    優先於 `per_source`。
    """
    if checker_mode not in CHECKER_MODES:
        raise ValueError(f"checker_mode 只能是 {CHECKER_MODES}：{checker_mode!r}")
    degraded = degraded if degraded is not None else []
    if per_source is None:
        per_source = get_settings().fact_checker_per_source
    if event_classes is None:
        event_classes = get_settings().fact_checker_event_classes
    clock = Clock(now)
    corr = correlation_id("T2", edition_date, story.id)
    source_ids = [item.item_id for item in evidence if item.item_id is not None]
    headline, deck, body, why = draft or reporter_draft(
        session, client, edition_date=edition_date, story=story, evidence=evidence, degraded=degraded,
    )
    version = write_story_version(
        session, story_id=story.id, run_variant=MAS, expected_latest=0, headline=headline, deck=deck,
        body=body, why_it_matters=why, source_ids=source_ids, status="draft", now=clock.tick(), sender="agent",
    )
    return _check_and_maybe_revise(
        session, edition_date=edition_date, story=story, evidence=evidence, version=version, client=client,
        clock=clock, corr=corr, degraded=degraded, per_source=per_source, checker_mode=checker_mode,
        day_context=day_context, event_classes=event_classes,
    )


def reporter_draft(session, client, *, edition_date, story, evidence, degraded) -> tuple[str, str, str, str]:
    """記者的 v1（headline, deck, body, why_it_matters）；沒有可用的回應就用模板稿。"""
    user = f"事件板塊：{story.section}。請寫一則稿，action 填 DRAFT。\n\n{_evidence_block(evidence)}"
    text = _ask(
        session, client, role="reporter", story_id=story.id, edition_date=edition_date,
        system=REPORTER_SYSTEM, user=user, schema=DRAFT_SCHEMA, temperature=0.3,
    )
    draft = _parse(text, _Draft)
    if draft is None or not draft.headline or not draft.body:
        if text is None and _quota_left(client) == 0 and "reporter" not in degraded:
            _degrade(degraded, "reporter")
        return _draft_from_template(evidence, story.kind)
    return draft.headline, draft.deck, draft.body, draft.why_it_matters


def _checker_relevance_prompt(version, evidence, bad, per_source: bool,
                              event_classes: bool = False) -> tuple[str, str, dict]:
    """可疑時那一次查核員請求（system, user, schema）。兩個開關都關時與 2026-11-01 前逐字相同。"""
    system = CHECKER_SYSTEM + CHECKER_RELEVANCE_SUFFIX
    user = f"稿件：{version.body}\n\n{_evidence_block(evidence)}"
    if not per_source and not event_classes:
        return system, user, CHECKER_SCHEMA
    listed = "、".join(f"S{index}" for index, _ in bad) or "（沒有）"
    user = f"程式點名的可疑來源：{listed}\n\n{user}"
    if event_classes:
        return system + CHECKER_EVENT_CLASS_SUFFIX, user, CHECKER_EVENT_CLASS_SCHEMA
    return system + CHECKER_PER_SOURCE_SUFFIX, user, CHECKER_PER_SOURCE_SCHEMA


def _check_and_maybe_revise(session, *, edition_date, story, evidence, version, client, clock, corr, degraded,
                            per_source: bool = False, checker_mode: str = "full",
                            day_context: EntityContext | None = None, event_classes: bool = False) -> StoryVersion:
    evidence_text = _evidence_text(evidence)
    use_llm = checker_mode == "full"
    bad = [] if checker_mode == "off" else call_tool(
        "fact_checker", "check_relevance", irrelevant_sources, evidence, day_context,
    )
    numbers = call_tool("fact_checker", "check_numbers", unsupported_numbers, version.body, evidence_text)
    assessment = None
    checker_call = None
    cleared: list[tuple[int, EvidenceItem]] = []
    if bad or numbers:
        # 可疑時才請查核員判斷。數字：程式結果不能被模型的 OK 覆蓋。
        # 來源：程式只看標題、抓不到中文與跨語言的同一事件（2026-10-31／11-01 把多來源稿刪到剩 1 家），
        # 所以查核員 LLM 判定同一事件時保留：逐來源判斷 KEEP 的，或舊格式回 OK（全部）；
        # REMOVE、CHALLENGE 或沒有判斷才照程式刪。
        if use_llm and "fact_checker" not in degraded and _quota_left(client) != 0:
            system, user, schema = _checker_relevance_prompt(version, evidence, bad, per_source, event_classes)
            assessment = _ask(
                session, client, role="fact_checker", story_id=story.id, edition_date=edition_date,
                system=system, user=user, schema=schema, temperature=0,
            )
            checker_call = last_record_id()
        elif use_llm and _quota_left(client) == 0:
            _degrade(degraded, "fact_checker")
        if bad:
            keep = checker_source_verdicts(assessment, [index for index, _ in bad])
            cleared = [x for x in bad if keep[x[0]]]
            bad = [x for x in bad if not keep[x[0]]]
    if bad or numbers:
        detail_parts = []
        if bad:
            listed = "、".join(f"S{index}（{item.display_name}｜{item.title}）" for index, item in bad)
            detail_parts.append(f"{listed}與事件沒有共同實體")
        if numbers:
            detail_parts.append(f"證據中找不到的數字：{', '.join(numbers[:5])}")
        payload = {
            "problem": "IRRELEVANT_SOURCE" if bad else "UNSUPPORTED_NUMBER",
            "detail": "；".join(detail_parts),
            "required_action": "刪除無關來源並確認正文沒有引用" if bad else "刪掉沒有出處的數字",
            "drop_sids": [index for index, _ in bad],
            "llm_assessment": assessment,
        }
        if cleared:
            payload |= _cleared_payload(cleared)
        message = post_message(
            session, run_variant=MAS, edition_date=edition_date, sender="fact_checker", recipient="reporter",
            type="CHALLENGE", now=clock.tick(), story_id=story.id, target_version=version.version,
            correlation_id=corr, payload=payload, llm_call_id=checker_call,
        )
        if claim_message(session, message.id):
            mark_handled(session, message.id)
        kept = [item for index, item in enumerate(evidence, start=1) if index not in {i for i, _ in bad}]
        return _revise(session, edition_date=edition_date, story=story, evidence=kept, removed=[item for _, item in bad],
                       version=version, client=client, clock=clock, corr=corr, challenge=message, degraded=degraded,
                       checker_mode=checker_mode, day_context=day_context)
    # 百分比那一問只有查核員 LLM 能答；實驗二的 off／program 兩組不問、也不因為「LLM 停了」而 HOLD。
    percents = _percent_values(evidence, version.body) if use_llm else set()
    if cleared and checker_says_same_event(assessment):
        # 查核員這次已經看過整篇（含數字）且回 OK，不再為百分比多問一次。
        percents = set()
    if len(percents) >= 2 and "fact_checker" not in degraded and _quota_left(client) != 0:
        return _checker_llm(
            session, edition_date=edition_date, story=story, evidence=evidence, version=version, client=client,
            clock=clock, corr=corr, degraded=degraded,
        )
    if len(percents) >= 2 and (_quota_left(client) == 0 or "fact_checker" in degraded):
        if "fact_checker" not in degraded:
            _degrade(degraded, "fact_checker")
        post_message(
            session, run_variant=MAS, edition_date=edition_date, sender="system", recipient="human", type="HOLD",
            now=clock.tick(), story_id=story.id, correlation_id=corr,
            payload={"detail": "查核員 LLM 已停，可疑稿一律 HOLD"},
        )
        return latest_version(session, story.id) or version
    version.status = "checked"
    session.flush()
    release = {"detail": "重驗：來源都有共同實體、數字都找得到"}
    if cleared:
        listed = "、".join(f"S{index}" for index, _ in cleared)
        release = {
            "detail": f"重驗：{listed} 與 S1 沒有共同名字，查核員判定同一事件，保留；數字都找得到",
            "llm_assessment": assessment, **_cleared_payload(cleared),
        }
    post_message(
        session, run_variant=MAS, edition_date=edition_date, sender="system", recipient="eic", type="RELEASE",
        now=clock.tick(), story_id=story.id, target_version=version.version, correlation_id=corr,
        payload=release, llm_call_id=checker_call if cleared else None,
    )
    # RELEASE 不該把 checked 改掉；hold_story 只在 HOLD。system RELEASE 是放行紀錄。
    version.status = "checked"
    session.flush()
    return version


def _revise(session, *, edition_date, story, evidence, removed, version, client, clock, corr, challenge, degraded,
            checker_mode: str = "full", day_context: EntityContext | None = None) -> StoryVersion:
    user = (
        f"查核員 CHALLENGE：{json.dumps(challenge.payload, ensure_ascii=False)}\n"
        f"請刪除被點名的來源後重寫，action 填 REVISE。\n\n{_evidence_block(evidence)}"
    )
    text = _ask(
        session, client, role="reporter", story_id=story.id, edition_date=edition_date,
        system=REPORTER_SYSTEM, user=user, schema=DRAFT_SCHEMA, temperature=0.3,
    )
    reporter_call = last_record_id()
    draft = _parse(text, _Draft)
    if draft is None or draft.action == "REBUT":
        # 反駁要查核員 LLM 裁決；off／program 兩組沒有查核員 LLM，照程式結果用模板稿。
        if draft is not None and draft.action == "REBUT" and checker_mode == "full":
            post_message(
                session, run_variant=MAS, edition_date=edition_date, sender="reporter", recipient="fact_checker",
                type="REBUT", now=clock.tick(), story_id=story.id, correlation_id=corr,
                payload={"reason": draft.reason, "target_version": version.version}, llm_call_id=reporter_call,
            )
            return _checker_llm(
                session, edition_date=edition_date, story=story, evidence=evidence, version=version, client=client,
                clock=clock, corr=corr, degraded=degraded, rebut=draft.reason,
            )
        headline, deck, body, why = _draft_from_template(evidence, story.kind)
    else:
        headline, deck, body, why = draft.headline, draft.deck, draft.body, draft.why_it_matters
        if any((item.title or "")[:12] and (item.title or "")[:12] in body for item in removed):
            headline, deck, body, why = _draft_from_template(evidence, story.kind)
    new = write_story_version(
        session, story_id=story.id, run_variant=MAS, expected_latest=version.version, headline=headline, deck=deck,
        body=body, why_it_matters=why, source_ids=[item.item_id for item in evidence if item.item_id is not None],
        status="draft", caused_by_message_id=challenge.id, now=clock.tick(), sender="agent",
    )
    done = post_message(
        session, run_variant=MAS, edition_date=edition_date, sender="reporter", recipient="fact_checker",
        type="REVISION_DONE", now=clock.tick(), story_id=story.id, correlation_id=corr,
        payload={"new_version": new.version, "change": f"來源改為 {len(evidence)} 家"}, llm_call_id=reporter_call,
    )
    if claim_message(session, done.id):
        mark_handled(session, done.id)
    keep = cleared_item_ids(session, story.id)
    still_irrelevant = [] if checker_mode == "off" else [
        x for x in irrelevant_sources(evidence, day_context) if x[1].item_id not in keep
    ]
    still_bad = still_irrelevant or unsupported_numbers(
        new.body, " ".join(f"{item.title} {item.summary}" for item in evidence)
    )
    if still_bad:
        post_message(
            session, run_variant=MAS, edition_date=edition_date, sender="fact_checker", recipient="reporter",
            type="CHALLENGE", now=clock.tick(), story_id=story.id, target_version=new.version, correlation_id=corr,
            payload={"problem": "STILL_BAD", "detail": "修訂後仍有問題"},
        )
        return latest_version(session, story.id) or new
    new.status = "checked"
    session.flush()
    post_message(
        session, run_variant=MAS, edition_date=edition_date, sender="system", recipient="reporter", type="RELEASE",
        now=clock.tick(), story_id=story.id, target_version=new.version, correlation_id=corr,
        payload={"detail": f"重驗：{len(evidence)} 個來源都有共同實體、數字都找得到"},
    )
    new.status = "checked"
    session.flush()
    return new


def _checker_llm(session, *, edition_date, story, evidence, version, client, clock, corr, degraded, rebut: str = "") -> StoryVersion:
    user = (
        f"事件標題：{evidence[0].title if evidence else ''}\n稿件：{version.body}\n"
        + (f"記者反駁：{rebut}\n" if rebut else "")
        + _evidence_block(evidence)
    )
    text = _ask(
        session, client, role="fact_checker", story_id=story.id, edition_date=edition_date,
        system=CHECKER_SYSTEM, user=user, schema=CHECKER_SCHEMA, temperature=0,
    )
    checker_call = last_record_id()
    parsed = _parse(text, _Checker)
    if parsed is None:
        if "fact_checker" not in degraded and text is None:
            _degrade(degraded, "fact_checker")
        post_message(
            session, run_variant=MAS, edition_date=edition_date, sender="system", recipient="human", type="HOLD",
            now=clock.tick(), story_id=story.id, correlation_id=corr,
            payload={"detail": "查核員沒有給出可用的判斷，HOLD"},
        )
        return latest_version(session, story.id) or version
    if parsed.action != "CHALLENGE":
        version.status = "checked"
        session.flush()
        return version
    message = post_message(
        session, run_variant=MAS, edition_date=edition_date, sender="fact_checker", recipient="reporter",
        type="CHALLENGE", now=clock.tick(), story_id=story.id, target_version=version.version, correlation_id=corr,
        payload={"problem": parsed.problem, "detail": parsed.detail, "required_action": parsed.required_action},
        llm_call_id=checker_call,
    )
    if message.type == "HOLD":
        return latest_version(session, story.id) or version
    if claim_message(session, message.id):
        mark_handled(session, message.id)
    follow = (
        f"查核員再 CHALLENGE：{parsed.detail}。要求：{parsed.required_action}。"
        f"請改稿，action 填 REVISE。\n\n{_evidence_block(evidence)}"
    )
    text = _ask(
        session, client, role="reporter", story_id=story.id, edition_date=edition_date,
        system=REPORTER_SYSTEM, user=follow, schema=DRAFT_SCHEMA, temperature=0.3,
    )
    reporter_call = last_record_id()
    draft = _parse(text, _Draft)
    if draft is not None and draft.action == "REBUT":
        post_message(
            session, run_variant=MAS, edition_date=edition_date, sender="reporter", recipient="fact_checker",
            type="REBUT", now=clock.tick(), story_id=story.id, correlation_id=corr, payload={"reason": draft.reason},
            llm_call_id=reporter_call,
        )
        return _checker_llm(
            session, edition_date=edition_date, story=story, evidence=evidence, version=version, client=client,
            clock=clock, corr=corr, degraded=degraded, rebut=draft.reason,
        )
    if draft is None or not draft.body:
        headline, deck, body, why = version.headline, version.deck or "", version.body, version.why_it_matters or ""
    else:
        headline, deck, body, why = draft.headline or version.headline, draft.deck, draft.body, draft.why_it_matters
    new = write_story_version(
        session, story_id=story.id, run_variant=MAS, expected_latest=version.version, headline=headline, deck=deck,
        body=body, why_it_matters=why, source_ids=list(version.source_ids or []), status="draft",
        caused_by_message_id=message.id, now=clock.tick(), sender="agent",
    )
    post_message(
        session, run_variant=MAS, edition_date=edition_date, sender="reporter", recipient="fact_checker",
        type="REVISION_DONE", now=clock.tick(), story_id=story.id, correlation_id=corr,
        payload={"new_version": new.version, "change": parsed.required_action}, llm_call_id=reporter_call,
    )
    new.status = "checked"
    session.flush()
    return new


def apply_decision(
    session: Session,
    *,
    edition_date: date,
    decision: _Decision,
    message: AgentMessage,
    now: datetime,
    hold_ids: set[int],
    section_links: list[tuple[str, int, str]] | None = None,
    min_front: int = 1,
) -> int | None:
    """決定合規則寫下一版 page_plan。不合規則把訊息標成 rejected，不改版面。"""
    problems = _decision_problems(decision, hold_ids, min_front)
    previous = session.scalar(select(PagePlan).where(
        PagePlan.edition_date == edition_date, PagePlan.run_variant == MAS
    ).order_by(PagePlan.plan_version.desc()))
    chosen = [i for i in [decision.lead, *decision.second, *decision.briefs] if i is not None]
    if previous is not None:
        allowed = {slot["story_id"] for slots in previous.slots.get("sections", {}).values() for slot in slots}
        if any(i not in allowed for i in chosen):
            problems.append("頭版只能從本期正式稿選擇")
    if problems:
        message.status = "rejected"
        message.payload = {**(message.payload or {}), "program_reason": "；".join(problems)}
        session.flush()
        return None
    slots = {
        "front": {"lead": decision.lead, "second": list(decision.second), "briefs": list(decision.briefs)},
        "sections": {},
    }
    if previous is not None:
        for section, entries in previous.slots.get("sections", {}).items():
            slots["sections"][section] = [
                {**slot, "display": "link" if slot["story_id"] in chosen else "full"}
                for slot in entries if slot["story_id"] not in hold_ids
            ]
    for link in decision.links:
        section = link.get("section")
        if section:
            if link.get("story_id") not in chosen or section not in SECTIONS:
                continue
            entries = slots["sections"].setdefault(section, [])
            if not any(slot["story_id"] == link["story_id"] for slot in entries):
                entries.append({"story_id": link["story_id"], "display": "link", "label": link.get("label") or ""})
    for section, story_id, label in section_links or []:
        slots["sections"].setdefault(section, []).append({"story_id": story_id, "display": "link", "label": label})
    plan = add_page_plan(
        session, edition_date=edition_date, run_variant=MAS, slots=slots, now=now, decided_by_message_id=message.id,
    )
    message.status = "handled"
    session.flush()
    return plan.id


def slots_from_pitches(pitches: list[Pitch]) -> dict:
    front = list(dict.fromkeys(p.story_id for p in pitches if p.priority == "front"))[:FRONT_CAPACITY]
    sections: dict[str, list] = {}
    for pitch in pitches:
        if pitch.story_id in front:
            sections.setdefault(pitch.section, []).append({
                "story_id": pitch.story_id, "display": "link", "label": pitch.angle,
            })
        else:
            sections.setdefault(pitch.section, []).append({"story_id": pitch.story_id, "display": "full"})
    return {
        "front": {
            "lead": front[0] if front else None,
            "second": front[1:5],
            "briefs": front[5:FRONT_CAPACITY],
        },
        "sections": sections,
    }


def run_mas(
    session: Session,
    *,
    edition_date: date,
    snapshot,
    registry,
    client,
    now: datetime,
    pitches: list[Pitch] | None = None,
) -> MasResult:
    """從一份快照跑 M 組。測試可傳入 pitches，跳過主編的模型呼叫。"""
    result = MasResult()
    recover_claimed(session, edition_date, MAS)
    names = {source.id: source.name for source in registry.sources}
    domains = registry_domains(registry)
    context = None
    if get_settings().mas_full_evidence:
        domains |= article_domains(session, registry, now)
        context = title_context(session, now, load_lexicon(), registry.disabled_source_ids())
    checker_context = None
    if get_settings().fact_checker_zh_fragments:
        checker_context = context or title_context(session, now, load_lexicon(), registry.disabled_source_ids())
    clock = Clock(now)
    with bind_log_session(session):
        existing = {
            row.keeper_cluster_id: row
            for row in session.scalars(select(Story).where(Story.edition_date == edition_date, Story.run_variant == MAS))
        }
        stories = dict(existing)
        evidence_of: dict[int, list[EvidenceItem]] = {}
        packs: dict[int, list[EvidenceItem]] = {}

        def pack_items(raw) -> list[EvidenceItem]:
            keeper = raw["keeper_cluster_id"]
            if keeper not in packs:
                pack: EvidencePack = build_evidence_from_ids(
                    session, list(raw.get("evidence_item_ids") or []), names,
                    anchor_item_id=raw.get("anchor_item_id"), allowed_domains=domains, context=context,
                )
                packs[keeper] = pack.items
            return packs[keeper]

        # P3-1：自動選稿時只為分版主編看得到的候選建 Story（每期約 4,800 → 24），見 mas_story_keepers；
        # 呼叫端自己給 pitches（測試）時照舊全部建列，外部指定的 story_id 才找得到。
        wanted = set(mas_story_keepers(snapshot.candidates, existing, pack_items)) if pitches is None else None
        for raw in snapshot.candidates:
            keeper = raw["keeper_cluster_id"]
            story = stories.get(keeper)
            if story is None:
                if wanted is not None and keeper not in wanted:
                    continue
                story = add_story(session, edition_date=edition_date, run_variant=MAS, spec=raw)
                stories[keeper] = story
            evidence_of[story.id] = _attach_fulltext(session, pack_items(raw))
        automatic = pitches is None
        pitch_calls: dict[str, int | None] = {}
        pitch_reasons: dict[int, str] = {}
        if automatic:
            pitches = _section_pitches(session, edition_date, list(stories.values()), evidence_of, client, pitch_calls,
                                       pitch_reasons, result.layout_log)
        pitches = guard_pitches(pitches, evidence_of, result.injection_log)
        for pitch in pitches:
            post_message(
                session, run_variant=MAS, edition_date=edition_date, sender=pitch.sender, recipient="eic",
                type="PITCH", now=clock.tick(), story_id=pitch.story_id,
                payload={"section": pitch.section, "angle": pitch.angle, "priority": pitch.priority,
                         **({"reason": pitch_reasons[pitch.story_id]} if pitch.story_id in pitch_reasons else {})},
                llm_call_id=pitch_calls.get(pitch.section),
            )
        if automatic:
            pitches = _trim_edition(session, edition_date=edition_date, pitches=pitches, stories=stories,
                                    evidence_of=evidence_of, reasons=pitch_reasons, client=client, clock=clock,
                                    result=result)
        hold_ids: set[int] = set()
        for pitch in pitches:
            story = session.get(Story, pitch.story_id)
            if story is None:
                continue
            evidence = evidence_of.get(pitch.story_id) or []
            version = latest_version(session, story.id)
            if version is None and evidence:
                version = review_one(
                    session, edition_date=edition_date, story=story, evidence=evidence, client=client,
                    now=clock.tick(), degraded=result.degraded, day_context=checker_context,
                )
            if version is not None and version.status == "hold":
                hold_ids.add(story.id)
        safe_pitches = [p for p in pitches if p.story_id not in hold_ids]
        if automatic:
            plan = add_page_plan(session, edition_date=edition_date, run_variant=MAS,
                                 slots=slots_from_pitches(safe_pitches), now=clock.tick())
            result.page_plan_ids.append(plan.id)
        more_interaction = automatic and get_settings().mas_more_interaction
        if automatic and not more_interaction:
            # desk-v3 C2 開啟時改成頭版排定後才審（_page_review），這裡的預審不送
            layout = _ask(session, client, role="layout_editor", story_id=None, edition_date=edition_date,
                          system="你是版面編輯。只檢查頭版容量、重複與版別平衡，不能新增事實。只回傳 JSON。",
                          user=json.dumps([p.__dict__ for p in safe_pitches], ensure_ascii=False),
                          schema=CHECKER_SCHEMA, temperature=0)
            post_message(session, run_variant=MAS, edition_date=edition_date, sender="layout_editor", recipient="eic",
                         type="PAGE_OBJECTION", now=clock.tick(), payload={"detail": layout or "程式檢查版面容量", "capacity": 6},
                         llm_call_id=last_record_id())
        conflicts = _conflicts(pitches)
        front = [p for p in pitches if p.priority == "front" and p.story_id not in hold_ids]
        if conflicts:
            _resolve_t1(session, edition_date=edition_date, conflicts=conflicts, client=client, clock=clock,
                        hold_ids=hold_ids, result=result, pitches=safe_pitches, evidence_of=evidence_of)
        elif automatic or len(front) > FRONT_CAPACITY:
            _resolve_t3(session, edition_date=edition_date, front=front, client=client, clock=clock,
                        hold_ids=hold_ids, result=result, evidence_of=evidence_of)
        else:
            plan = add_page_plan(
                session, edition_date=edition_date, run_variant=MAS, slots=slots_from_pitches(
                    [p for p in pitches if p.story_id not in hold_ids]
                ), now=clock.tick(),
            )
            result.page_plan_ids.append(plan.id)
        if more_interaction:
            _page_review(session, edition_date=edition_date, client=client, clock=clock, hold_ids=hold_ids,
                         evidence_of=evidence_of, result=result)
            _eic_revisions(session, edition_date=edition_date, client=client, clock=clock, hold_ids=hold_ids,
                           evidence_of=evidence_of, result=result, day_context=checker_context)
        if _quota_left(client) == 0:
            _degrade(result.degraded, "reporter")
        _maybe_shorten_lead(session, edition_date=edition_date, client=client, clock=clock, degraded=result.degraded)
        if "copy_editor" not in result.degraded and _quota_left(client) != 0:
            _copy_edit_front(session, edition_date=edition_date, client=client, clock=clock, degraded=result.degraded,
                             context=context)
        elif _quota_left(client) == 0 and "copy_editor" not in result.degraded:
            result.degraded.append("copy_editor")
        if get_settings().mas_noise_check:
            noise_hold(session, edition_date=edition_date, story_ids=[p.story_id for p in pitches], clock=clock,
                       result=result)
        settle_messages(session, edition_date, MAS)
    return result


NOISE_FIELDS = ("headline", "deck", "body", "why_it_matters")


def noise_hold(session: Session, *, edition_date: date, story_ids, clock, result: MasResult) -> dict[int, dict]:
    """MAS_NOISE_CHECK：文稿編輯之後掃每篇最新版，欄位混進模型雜訊就 system HOLD（不重試、不多呼叫模型）。

    放在最後一步，記者、修稿、總編退稿、文稿編輯產生的版本都會掃到。HOLD 的稿已在版面上的不移出，
    跟其他 HOLD 稿一樣發行時只出標題（「暫扣」）。訊息超過一期上限被標 expired 時仍直接 hold，不讓雜訊稿出全文。
    """
    found: dict[int, dict] = {}
    for story_id in dict.fromkeys(story_ids):
        version = latest_version(session, story_id)
        if version is None or version.status == "hold" or not (version.body or "").strip():
            continue
        hits = story_noise({name: getattr(version, name) for name in NOISE_FIELDS})
        if not hits:
            continue
        message = post_message(
            session, run_variant=MAS, edition_date=edition_date, sender="system", recipient="human", type="HOLD",
            now=clock.tick(), story_id=story_id, target_version=version.version,
            payload={"detail": "稿件欄位混進模型推理文字或 JSON 殘渣，HOLD", "noise": hits},
        )
        if message.status != "pending":
            hold_story(session, story_id)
        found[story_id] = hits
        logger.warning("model noise HOLD: edition=%s story=%s fields=%s", edition_date, story_id, sorted(hits))
    result.noise_log.update(found)
    return found


def rich_fields(evidence: list[EvidenceItem] | None) -> dict:
    """MAS_RICH_CONTEXT 開啟時給主編／總編的額外欄位：S1 摘要（限長）、媒體名、家數。

    證據包有注入標記時不給摘要（只給媒體名），避免把來源裡的指示送進編輯決策。
    """
    evidence = evidence or []
    outlets: list[str] = []
    for item in evidence:
        name = item.display_name
        if name not in outlets:
            outlets.append(name)
    summary = ""
    if evidence and not evidence_has_injection(evidence):
        summary = (evidence[0].summary or "").strip()[:RICH_SUMMARY_CHARS]
    return {"summary": summary, "outlets": outlets, "outlet_count": len(outlets)}


GLOBAL_TOP_N = 10  # 分版主編提示裡的 global_top10


def mas_story_keepers(candidates: list[dict], existing: dict[int, Story], has_evidence) -> list[int]:
    """M 組要新建 `Story` 列的 keeper_cluster_id（依快照順序；已存在的列不在內）。

    分版主編（固定名額與 `MAS_OPEN_LAYOUT`）只看得到下面三種稿，其他候選不建列：
    - 各內版 `section_pool`：有證據、kind 合規，依 (kind, -score, id) 取配額 × `DESK_POOL_PER_SECTION`；
      `_default_pitches`（`select_articles`）選的稿是它的子集。
    - 全站分數前 `GLOBAL_TOP_N`（三個內版，不論有沒有證據）。
    - 重跑時已存在的列（照舊保留）。
    `has_evidence(raw)` 回傳該候選的證據包（非空才算有證據）。新列的 id 依快照順序遞增、排在既有列之後，
    這裡用 (0, 既有 id)／(1, 快照位置) 代替 id，所以挑出來的稿、平手順序都和「全部建列再挑」相同。
    """
    by_keeper = {raw["keeper_cluster_id"]: raw for raw in candidates}
    rows: list[tuple] = []  # (keeper, section, kind, score, id 排序鍵)
    for keeper, story in existing.items():
        rows.append((keeper, story.section, story.kind, story.score, (0, story.id)))
    for index, raw in enumerate(candidates):
        keeper = raw["keeper_cluster_id"]
        if keeper not in existing:
            rows.append((keeper, raw["section"], raw["kind"], raw.get("score") or 0, (1, index)))
    memo: dict[int, bool] = {}

    def evidenced(keeper: int) -> bool:
        if keeper not in memo:
            raw = by_keeper.get(keeper)
            memo[keeper] = raw is not None and bool(has_evidence(raw))
        return memo[keeper]

    wanted: set[int] = set()
    for section, quota in SECTION_QUOTAS.items():
        eligible = sorted((r for r in rows if r[1] == section and r[2] in SECTION_KINDS[section]),
                          key=lambda r: (_KIND_RANK.get(r[2], 9), -r[3], r[4]))
        taken = 0
        for row in eligible:
            if taken >= quota * DESK_POOL_PER_SECTION:
                break
            if evidenced(row[0]):
                wanted.add(row[0])
                taken += 1
    wanted.update(r[0] for r in sorted((r for r in rows if r[1] in SECTIONS), key=lambda r: -r[3])[:GLOBAL_TOP_N])
    return [raw["keeper_cluster_id"] for raw in candidates
            if raw["keeper_cluster_id"] in wanted and raw["keeper_cluster_id"] not in existing]


def _default_pitches(stories: list[Story], evidence_of: dict[int, list[EvidenceItem]]) -> list[Pitch]:
    by_id = {story.id: story for story in stories if evidence_of.get(story.id)}
    selections = select_articles([
        ScoredCluster(story.id, story.section, story.kind, story.score) for story in by_id.values()
    ])
    return [Pitch(section=sel.section, story_id=sel.cluster.cluster_id, angle=sel.section,
                  priority="front" if sel.is_front else "section") for sel in selections]


_KIND_RANK = {"report": 0, "single_source": 1, "social": 2}


def section_pool(stories: list[Story], evidence_of: dict[int, list[EvidenceItem]], section: str) -> list[Story]:
    """開放版面時給分版主編的候選：本版有證據、kind 合規的稿，依選題順序取配額 × DESK_POOL_PER_SECTION。"""
    eligible = [s for s in stories if s.section == section and s.kind in SECTION_KINDS[section] and evidence_of.get(s.id)]
    eligible.sort(key=lambda s: (_KIND_RANK.get(s.kind, 9), -s.score, s.id))
    return eligible[: SECTION_QUOTAS[section] * DESK_POOL_PER_SECTION]




def format_trace(session: Session, edition_date: date, run_variant: str, cluster_id: int | None = None) -> str:
    """印出一期（或單一 cluster）的訊息與版本。cluster_id 在這裡換成 story_id。"""
    story_id = None
    if cluster_id is not None:
        story = session.scalar(
            select(Story).where(
                Story.edition_date == edition_date,
                Story.run_variant == run_variant,
                Story.keeper_cluster_id == cluster_id,
            )
        )
        if story is None:
            return f"找不到 {edition_date} {run_variant} cluster {cluster_id}"
        story_id = story.id
    messages = session.scalars(
        select(AgentMessage)
        .where(AgentMessage.edition_date == edition_date, AgentMessage.run_variant == run_variant)
        .order_by(AgentMessage.created_at, AgentMessage.id)
    ).all()
    if story_id is not None:
        messages = [row for row in messages if row.story_id in (story_id, None)]
    lines = []
    for row in messages:
        lines.append(
            f"{row.created_at.isoformat()} {row.sender_role} → {row.recipient_role} {row.type} "
            f"story={row.story_id} status={row.status} {json.dumps(row.payload, ensure_ascii=False)}"
        )
    if story_id is not None:
        versions = session.scalars(
            select(StoryVersion).where(StoryVersion.story_id == story_id).order_by(StoryVersion.version)
        ).all()
        for version in versions:
            lines.append(f"version v{version.version} status={version.status} headline={version.headline}")
    return "\n".join(lines)

"""準備與發行綜合日報。

準備分三段：先在一個 session 讀資料、評分、選題、組證據；接著在任何 DB
交易之外呼叫 LLM（可能要幾分鐘，不能讓每 15 分鐘的收集等鎖）；最後
在另一個 session 一次寫入整期。發行只送已準備好的版次，且不重送。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import shutil
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from sqlalchemy import select, func

from ..collection.clustering import ClusterRunStats, cluster_recent_items
from ..collection.entities import EntityContext, MergeRules, load_lexicon
from ..config import LLM_PROVIDERS, get_settings
from ..db import session_scope
from ..llm.quota import SHADOW_PURPOSE, QuotaExhausted
from ..llm.records import bind_log_factory, bind_log_session, llm_log_meta
from ..models import DailyArticle, DailyEdition, DailySnapshot, LLMRecord, Story, StoryCluster, StoryVersion
from ..seeds.news_sources import SourceRegistry, load_registry
from .desk import DeskMerges, desk_merges
from .evidence import EvidenceItem, EvidencePack, build_evidence, build_evidence_from_ids, title_context
from .market import fetch_market_box
from .render import render_html, telegram_digest, write_history_index
from .scoring import ScoredCluster, Selection, apply_merges, desk_pool, score_candidates, select_articles, window_start_for
from .sections import rewrite_sections, rewrite_summary, select_briefs
from .store import (
    MAS,
    PIPELINE,
    add_page_plan,
    add_story,
    approve_story,
    clear_variant,
    freeze_candidates,
    hold_story,
    upsert_snapshot,
    write_story_version,
)
from .view import build_edition_view, view_from_edition
from .writer import DailyWriter, WrittenStory, finalize_story, review_story, template_story

logger = logging.getLogger(__name__)

FRONT_GROUP = "front"
LLM_WRITERS = ("codex", "gemini", "fake")
# 外層整版重寫最多 2 次；client 內部失敗再各重試 1 次，最壞一版吃 4 格額度（手冊 6.7）。
WRITE_ATTEMPTS = 2
RETRY_DELAY_SECONDS = 15.0


class DailyEditionError(RuntimeError):
    pass


@dataclass
class Planned:
    key: int
    selection: Selection
    evidence: list[EvidenceItem]
    # 組證據包時的紀錄（相關性過濾剔除的來源），會寫進稿件的 review_notes
    notes: list[str] = field(default_factory=list)


@dataclass
class EditionPlan:
    """撰稿前的一期：編輯會議合併後的全部候選、合併組、選上且有證據的稿件。"""

    candidates: list[ScoredCluster]
    candidate_count: int
    merged_groups: list[list[int]]
    planned: list[Planned]
    desk: DeskMerges | None = None
    # 證據包相關性過濾用的「當天素材」（聚合時間窗內的標題）
    context: EntityContext | None = None
    # 其他版只出頭版標題短訊（不呼叫 LLM），寫進 stats["briefs"]（手冊步驟 4）
    briefs: list[dict] = field(default_factory=list)
    snapshot_candidates: list[dict] | None = None


def _today() -> date:
    return datetime.now(ZoneInfo(get_settings().newsroom_delivery_timezone)).date()


def _editorial_meeting(
    session, scored, writer: DailyWriter | None, disabled_sources: frozenset[str] = frozenset()
) -> tuple[list, DeskMerges]:
    """跨語言同一事件：程式用譯名表＋共同實體合併；LLM（find_same_events）只當第二意見，
    它說合併的組也要程式確認有共同實體（手冊步驟 3 第 4 點）。LLM 失敗不擋出刊。"""
    pool = desk_pool(scored)
    llm_groups: list[list[int]] = []
    if writer is not None and pool:
        titles = dict(
            session.execute(
                select(StoryCluster.id, StoryCluster.title).where(StoryCluster.id.in_([s.cluster_id for s in pool]))
            ).all()
        )
        try:
            llm_groups = writer.find_same_events([(s.cluster_id, titles.get(s.cluster_id) or "") for s in pool])
        except Exception as exc:  # noqa: BLE001 — 編輯會議失敗不擋出刊，只是可能重複
            logger.warning("editorial meeting failed: %s", exc)
    desk = desk_merges(
        session,
        pool,
        llm_groups,
        lexicon=load_lexicon(),
        rules=MergeRules.from_settings(),
        disabled_sources=disabled_sources,
        context_cluster_ids=[s.cluster_id for s in scored],
    )
    for rejected in desk.rejected:
        logger.info("editorial meeting rejected merge: %s", rejected)
    return apply_merges(scored, desk.groups), desk


def _write_all(
    planned: list[Planned], sections: dict[str, str], writer: DailyWriter | None
) -> dict[int, WrittenStory]:
    groups: dict[str, list[Planned]] = {}
    for item in planned:
        group = FRONT_GROUP if item.selection.is_front else item.selection.section
        groups.setdefault(group, []).append(item)

    written: dict[int, WrittenStory] = {}
    for group, items in groups.items():
        generated: dict[int, WrittenStory] = {}
        failure = None
        if writer is not None:
            label = "頭版" if group == FRONT_GROUP else sections.get(group, group)
            for attempt in range(1, WRITE_ATTEMPTS + 1):
                try:
                    generated = writer.write(
                        label, [(p.key, p.selection.cluster.kind, p.evidence) for p in items]
                    )
                    failure = None
                    break
                except Exception as exc:  # noqa: BLE001 — JSON 壞掉、503 過載都值得重試；最後才退模板稿
                    failure = f"{writer.name} 撰稿失敗（{attempt} 次）：{type(exc).__name__}: {str(exc)[:160]}"
                    logger.warning("daily writer failed for %s: %s", group, failure)
                    if isinstance(exc, QuotaExhausted):
                        break  # 額度用完重試也沒用，直接退模板稿
                    if attempt < WRITE_ATTEMPTS:
                        time.sleep(RETRY_DELAY_SECONDS)
        for p in items:
            story = generated.get(p.key)
            notes = list(p.notes) + ([failure] if failure else [])
            if story is not None:
                problems = review_story(story, p.evidence)
                if problems:
                    notes += problems
                    story = None
            elif writer is not None and not failure:
                notes.append(f"{writer.name} 回應缺少這則")
            if story is None:
                story = template_story(p.evidence, p.selection.cluster.kind)
            story = finalize_story(story, p.evidence, p.selection.cluster.kind)
            story.review_notes = notes
            written[p.key] = story
    return written


class _SilentClient:
    """沒有模型時讓 MAS 退回模板稿。不連網、不執行 codex。"""

    model = "template"

    def complete(self, **kwargs):
        from types import SimpleNamespace

        return SimpleNamespace(content="", input_tokens=0, output_tokens=0, cached_tokens=0)


def evidence_packs_from_snapshot(session, snapshot, registry: SourceRegistry) -> list[tuple[int, list[int]]]:
    """同一份快照組出來的證據素材 id。不看素材現在屬於哪個 cluster。"""
    names = {source.id: source.name for source in registry.sources}
    candidates = snapshot.candidates if hasattr(snapshot, "candidates") else snapshot["candidates"]
    packs = []
    for raw in candidates:
        pack = build_evidence_from_ids(
            session,
            list(raw.get("evidence_item_ids") or []),
            names,
            anchor_item_id=raw.get("anchor_item_id"),
        )
        packs.append((raw["keeper_cluster_id"], [item.item_id for item in pack.items]))
    return packs


def layout_slots(entries: list[tuple[int, str, bool, int, int]]) -> dict:
    """手冊步驟 4 的版面：`entries`＝(story_id, 內版, 是否頭版, 頭版順位, 內版順位)。

    頭版 6 則是從三內版 12 篇裡標記的：頭版刊全文（第 1 則主稿、第 2–5 則次稿、第 6 則短訊位置，
    只差版型大小），所屬內版只放連結，同一篇全文只印一次。P 組與 M 組（`slots_from_pitches`）規則相同。
    """
    front = [e for e in sorted((e for e in entries if e[2]), key=lambda e: e[3])]
    ids = [e[0] for e in front]
    linked = set(ids)
    sections: dict[str, list] = {}
    for story_id, section, _, _, section_position in sorted(entries, key=lambda e: (e[1], e[4], e[0])):
        display = "link" if story_id in linked else "full"
        sections.setdefault(section, []).append({"story_id": story_id, "display": display})
    return {
        "front": {"lead": ids[0] if ids else None, "second": ids[1:5], "briefs": ids[5:]},
        "sections": sections,
    }


def _pipeline_slots(planned: list[Planned], story_ids: dict[int, int]) -> dict:
    return layout_slots([
        (
            story_ids[p.key], p.selection.section, p.selection.is_front, p.selection.position,
            p.selection.section_position or p.selection.position,
        )
        for p in planned
    ])


def _persist_pipeline(session, *, edition_date: date, plan: EditionPlan, planned, written, registry, now) -> None:
    """P 組把選題寫成 stories／story_versions／page_plans，並凍結全部候選。"""
    clear_variant(session, edition_date, PIPELINE)
    upsert_snapshot(
        session, edition_date, plan.snapshot_candidates if plan.snapshot_candidates is not None else freeze_candidates(session, plan.candidates, registry.disabled_source_ids()), now,
    )
    story_ids: dict[int, int] = {}
    for p in planned:
        story = add_story(
            session,
            edition_date=edition_date,
            run_variant=PIPELINE,
            spec={
                "keeper_cluster_id": p.selection.cluster.cluster_id,
                "merged_cluster_ids": list(p.selection.cluster.merged_ids),
                "section": p.selection.section,
                "kind": p.selection.cluster.kind,
                "score": p.selection.cluster.score,
            },
        )
        story_ids[p.key] = story.id
        text = written[p.key]
        write_story_version(
            session,
            story_id=story.id,
            run_variant=PIPELINE,
            expected_latest=0,
            headline=text.headline,
            deck=text.deck,
            body=text.body,
            why_it_matters=text.why_it_matters,
            source_ids=[item.item_id for item in p.evidence if item.item_id is not None],
            status="checked",
            now=now,
            sender="agent",
        )
    add_page_plan(
        session,
        edition_date=edition_date,
        run_variant=PIPELINE,
        slots=_pipeline_slots(planned, story_ids),
        now=now,
    )


def _mode(explicit: str | None) -> str:
    mode = explicit or getattr(get_settings(), "daily_mode", "pipeline")
    if mode not in (PIPELINE, MAS):
        raise ValueError(f"DAILY_MODE 只允許 pipeline／mas：{mode!r}")
    return mode


def story_evidence(
    session, cluster: ScoredCluster, registry: SourceRegistry, context: EntityContext | None = None
) -> EvidencePack:
    """一個（可能已合併的）事件的證據包；選題與回歸集都從這裡取，確保同一套規則。"""
    return build_evidence(
        session,
        cluster.all_ids,
        {s.id: s.name for s in registry.sources},
        registry.disabled_source_ids(),
        lexicon=load_lexicon(),
        context=context,
    )


def plan_edition(
    session, *, edition_date: date, now: datetime, writer: DailyWriter | None, registry: SourceRegistry
) -> EditionPlan:
    """評分 → 編輯會議（跨語言合併）→ 選題 → 證據包；不撰稿、不寫 DB。"""
    scored = score_candidates(
        session,
        edition_date=edition_date,
        now=now,
        general_sources=registry.general_source_ids(),
        disabled_sources=registry.disabled_source_ids(),
    )
    candidate_count = len(scored)
    scored = rewrite_sections(session, scored, registry=registry)  # 併版：兩岸、財經、教育社會改寫到三個內版
    scored, desk = _editorial_meeting(session, scored, writer, registry.disabled_source_ids())
    context = title_context(session, now, load_lexicon(), registry.disabled_source_ids())
    planned = []
    selections = select_articles(scored)
    for key, selection in enumerate(selections, start=1):
        pack = story_evidence(session, selection.cluster, registry, context)
        if pack.items:
            planned.append(Planned(key, selection, pack.items, pack.notes))
    briefs = select_briefs(scored, selections, lambda c: story_evidence(session, c, registry, context).items)
    return EditionPlan(scored, candidate_count, desk.groups, planned, desk, context, briefs)


def plan_from_snapshot(session, snapshot, registry) -> EditionPlan:
    raw = snapshot.candidates if hasattr(snapshot, "candidates") else snapshot["candidates"]
    candidates = [ScoredCluster(r["keeper_cluster_id"], r["section"], r["kind"], r["score"],
                                dict(r.get("signals") or {}), list(r.get("merged_cluster_ids") or [])) for r in raw]
    by_id = {r["keeper_cluster_id"]: r for r in raw}
    names = {s.id: s.name for s in registry.sources}
    def pack(c):
        r = by_id[c.cluster_id]
        return build_evidence_from_ids(session, r["evidence_item_ids"], names, anchor_item_id=r.get("anchor_item_id"))
    selections = select_articles(candidates)
    planned = []
    for key, selection in enumerate(selections, 1):
        evidence = pack(selection.cluster)
        if evidence.items:
            planned.append(Planned(key, selection, evidence.items, evidence.notes))
    briefs = select_briefs(candidates, selections, lambda c: pack(c).items)
    # 快照裡已經是編輯會議合併後的候選；合併組從 merged_cluster_ids 還原（desk 細節不在快照裡）
    merged_groups = [[c.cluster_id, *c.merged_ids] for c in candidates if c.merged_ids]
    return EditionPlan(candidates, len(candidates), merged_groups, planned, briefs=briefs, snapshot_candidates=raw)


def _write_edition_html(site_dir: str, edition_date: date, view) -> Path:
    path = Path(site_dir) / f"{edition_date.isoformat()}.html"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_html(view), encoding="utf-8")
    return path


def _draft_edition(
    session,
    *,
    edition_date: date,
    now: datetime,
    planned,
    written,
    writer,
    candidate_count: int,
    merged_groups,
    desk,
    sections: dict,
    market,
    llm_requests: int,
    run_variant: str,
    plan: EditionPlan | None = None,
) -> DailyEdition:
    edition = session.scalar(select(DailyEdition).where(DailyEdition.edition_date == edition_date))
    if edition is None:
        edition = DailyEdition(edition_date=edition_date, created_at=now)
        session.add(edition)
    elif edition.status in ("publishing", "published", "delivery_failed"):
        raise DailyEditionError(f"版次已是 {edition.status}，拒絕覆寫")
    edition.status = "drafting"
    edition.window_start = window_start_for(edition_date)
    edition.prepared_at = now
    edition.updated_at = now
    edition.articles.clear()
    session.flush()
    for p in planned:
        story = written[p.key]
        edition.articles.append(
            DailyArticle(
                cluster_id=p.selection.cluster.cluster_id,
                section=p.selection.section,
                position=p.selection.position,
                is_front=p.selection.is_front,
                kind=p.selection.cluster.kind,
                score=p.selection.cluster.score,
                signals=p.selection.cluster.signals,
                headline=story.headline,
                deck=story.deck,
                body=story.body,
                why_it_matters=story.why_it_matters,
                sources=[e.as_source() for e in p.evidence],
                writer=story.writer,
                review_notes=story.review_notes,
            )
        )
    ai_count = sum(1 for s in written.values() if s.writer != "template")
    if run_variant == MAS:
        edition.writer = "mas"
    elif not written:
        edition.writer = "template"
    else:
        edition.writer = (writer.name if writer else "template") if ai_count == len(written) else (
            "template" if not ai_count else "mixed"
        )
    edition.stats = {
        "run_variant": run_variant,
        "candidate_clusters": candidate_count,
        "merged_groups": merged_groups,
        "entity_merge_groups": desk.entity_groups if desk else [],
        "llm_merge_groups": desk.llm_groups if desk else [],
        "rejected_merges": desk.rejected if desk else [],
        "articles": len(written) or len(edition.articles),
        "ai_articles": ai_count,
        "template_articles": (len(written) - ai_count) if written else 0,
        "llm_requests": llm_requests,
        "sections": {k: sum(1 for p in planned if p.selection.section == k) for k in sections},
        "front_articles": sum(1 for p in planned if p.selection.is_front),
        "briefs": plan.briefs if plan else [],
        "section_rewrites": rewrite_summary(plan.candidates) if plan else {},
        "market": market,
    }
    edition.status = "drafted"
    edition.updated_at = now
    session.flush()
    return edition


def _finish_mas(
    session,
    *,
    edition_date,
    plan,
    registry,
    writer,
    now,
    settings,
    sections,
    market,
    llm_requests,
    candidate_count,
    merged_groups,
    desk,
) -> int:
    from .mas.orchestrator import run_mas

    clear_variant(session, edition_date, MAS)
    snapshot = upsert_snapshot(
        session, edition_date, plan.snapshot_candidates if plan.snapshot_candidates is not None else freeze_candidates(session, plan.candidates, registry.disabled_source_ids()), now,
    )
    client = getattr(writer, "client", None) or _SilentClient()
    result = run_mas(
        session, edition_date=edition_date, snapshot=snapshot, registry=registry, client=client, now=now,
    )
    view = build_edition_view(session, edition_date, MAS, sections, market=market, for_publish=False)
    if not view.articles:
        raise DailyEditionError("沒有可刊登的事件；請確認收集與聚合是否正常")
    edition = _draft_edition(
        session, edition_date=edition_date, now=now, planned=[], written={}, writer=writer,
        candidate_count=candidate_count, merged_groups=merged_groups, desk=desk, sections=sections,
        market=market, llm_requests=llm_requests, run_variant=MAS, plan=plan,
    )
    seen = set()
    for article in view.articles:
        if article.story_id in seen:
            continue
        seen.add(article.story_id)
        story = session.get(Story, article.story_id) if article.story_id else None
        if story is None:
            continue
        from .store import latest_version
        from .view import _sources_for
        version = latest_version(session, story.id)
        edition.articles.append(
            DailyArticle(
                cluster_id=story.keeper_cluster_id,
                section=story.section,
                position=article.position,
                is_front=article.is_front,
                kind=story.kind,
                score=story.score,
                signals={"merged_cluster_ids": list(story.merged_cluster_ids or [])},
                headline=version.headline,
                deck=version.deck,
                body=version.body,
                why_it_matters=version.why_it_matters,
                sources=_sources_for(session, story, version),
                writer="mas",
                review_notes=[],
            )
        )
    edition.stats = {
        **(edition.stats or {}),
        "articles": len(edition.articles),
        "front_articles": sum(1 for a in edition.articles if a.is_front),
        "sections": {k: sum(1 for a in edition.articles if a.section == k) for k in sections},
        "degraded": list(result.degraded),
        "injection_log": list(result.injection_log),
        "llm_requests": session.scalar(select(func.count()).select_from(LLMRecord).where(
            LLMRecord.edition_date == edition_date, LLMRecord.run_variant == MAS,
            LLMRecord.provider == "codex")),
        "role_calls": dict(session.execute(select(LLMRecord.role, func.count()).where(
            LLMRecord.edition_date == edition_date, LLMRecord.run_variant == MAS,
            LLMRecord.provider == "codex").group_by(LLMRecord.role)).all()),
        "run_variant": MAS,
    }
    session.flush()
    view.stats = edition.stats
    path = _write_edition_html(settings.daily_site_dir, edition_date, view)
    edition.html_path = str(path)
    write_history_index(settings.daily_site_dir)
    logger.info("mas edition %s drafted: articles=%d degraded=%s", edition_date, len(edition.articles), result.degraded)
    return edition.id


def _publication_view(session, edition: DailyEdition, sections: dict, mode: str):
    variant = MAS if mode == MAS else PIPELINE
    try:
        return build_edition_view(
            session,
            edition.edition_date,
            variant,
            sections,
            market=(edition.stats or {}).get("market"),
            stats=edition.stats,
            published_at=edition.published_at,
            for_publish=mode == MAS,
        )
    except LookupError:
        return view_from_edition(edition, sections)


def prepare_daily(
    edition_date: date,
    *,
    writer_mode: str | None = None,
    refresh: bool = False,
    now: datetime | None = None,
    writer: DailyWriter | None = None,
    mode: str | None = None,
    shadow: bool = False,
    snapshot=None,
) -> int:
    """冪等準備一期日報，回傳 edition id；不發送。

    `writer`：直接指定撰稿者（回歸集用 replay client），此時不看 `writer_mode`、不找 codex binary。
    """
    settings = get_settings()
    now = now or datetime.now(timezone.utc)
    mode = PIPELINE if shadow else _mode(mode)
    if writer is None:
        writer_mode = writer_mode or settings.daily_writer
        if writer_mode not in LLM_PROVIDERS:
            raise ValueError(f"撰稿 provider 只允許 {'/'.join(LLM_PROVIDERS)}：{writer_mode!r}")
        if writer_mode == "gemini" and not settings.gemini_api_key:
            writer_mode = "template"
        if writer_mode == "codex" and shutil.which(settings.codex_bin) is None:
            logger.warning("codex binary not found at %s; falling back to template", settings.codex_bin)
            writer_mode = "template"
    registry = load_registry(settings.news_sources_path)
    sections = registry.sections

    with session_scope() as session:
        existing = session.scalar(select(DailyEdition).where(DailyEdition.edition_date == edition_date))
        if existing is not None and not shadow:
            if existing.status in ("publishing", "published", "delivery_failed"):
                return existing.id
            if existing.status == "drafted" and not refresh:
                return existing.id
        if writer is None and writer_mode in LLM_WRITERS:
            # 影子版的額度另外記在 SHADOW_PURPOSE，受 DAILY_SHADOW_LLM_LIMIT 限制（保護 M 組的額度）
            writer = DailyWriter(writer_mode, purpose=SHADOW_PURPOSE) if shadow else DailyWriter(writer_mode)
        with bind_log_session(session), llm_log_meta(role="desk", run_variant=mode, edition_date=edition_date):
            if snapshot is None:
                plan = plan_edition(session, edition_date=edition_date, now=now, writer=writer, registry=registry)
            else:
                plan = plan_from_snapshot(session, snapshot, registry)
        candidate_count, merged_groups, planned = plan.candidate_count, plan.merged_groups, plan.planned
        desk = plan.desk
    if not planned:
        raise DailyEditionError("沒有可刊登的事件；請確認收集與聚合是否正常")

    if mode == PIPELINE:
        with bind_log_factory(session_scope), llm_log_meta(role="writer", run_variant=PIPELINE, edition_date=edition_date, purpose="daily"):
            written = _write_all(planned, sections, writer)
    else:
        written = {}
    llm_requests = writer.requests if writer else 0
    market = fetch_market_box()

    with session_scope() as session:
        if mode == MAS:
            return _finish_mas(
                session, edition_date=edition_date, plan=plan, registry=registry, writer=writer,
                now=now, settings=settings, sections=sections, market=market, llm_requests=llm_requests,
                candidate_count=candidate_count, merged_groups=merged_groups, desk=desk,
            )
        _persist_pipeline(
            session, edition_date=edition_date, plan=plan, planned=planned, written=written, registry=registry, now=now,
        )
        if shadow:
            view = build_edition_view(
                session, edition_date, PIPELINE, sections, market=market,
                stats={"market": market, "briefs": plan.briefs},
            )
            path = Path(settings.daily_site_dir) / "shadow" / f"{edition_date.isoformat()}.html"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(render_html(view), encoding="utf-8")
            logger.info("pipeline shadow %s written to %s", edition_date, path)
            return 0
        edition = _draft_edition(
            session, edition_date=edition_date, now=now, planned=planned, written=written, writer=writer,
            candidate_count=candidate_count, merged_groups=merged_groups, desk=desk, sections=sections,
            market=market, llm_requests=llm_requests, run_variant=PIPELINE, plan=plan,
        )
        view = view_from_edition(edition, sections)
        path = _write_edition_html(settings.daily_site_dir, edition_date, view)
        edition.html_path = str(path)
        write_history_index(settings.daily_site_dir)
        logger.info(
            "daily edition %s drafted: articles=%d ai=%d template=%d",
            edition_date, len(written), edition.stats["ai_articles"], edition.stats["template_articles"],
        )
        return edition.id


def _variant_has_stories(session, edition_date: date, variant: str) -> bool:
    return session.scalar(
        select(func.count()).select_from(StoryVersion).join(Story, StoryVersion.story_id == Story.id)
        .where(Story.edition_date == edition_date, Story.run_variant == variant)
    ) > 0


def export_annotation(edition_date: date, out_root: str | Path) -> Path | None:
    """當期盲計稿與抽查稿寫到 `out_root/YYYY-MM-DD/`（手冊步驟 11 第 4 點、9.2）。

    P、M 都有稿才匯出。給標註員的是 blind.txt、spot-check.txt、mapping.sha256；
    對照表本體放 `_private/mapping.json`（不給標註員；annotation/ 已 gitignore）。
    """
    from .blind import export_blind_count, spot_check_sheet

    with session_scope() as session:
        if not (_variant_has_stories(session, edition_date, PIPELINE) and _variant_has_stories(session, edition_date, MAS)):
            logger.info("annotation export %s skipped: P or M has no stories", edition_date)
            return None
        text, mapping, digest = export_blind_count(session, [edition_date])
        spot = spot_check_sheet(session, edition_date)
    out = Path(out_root) / edition_date.isoformat()
    private = out / "_private"
    private.mkdir(parents=True, exist_ok=True)
    (out / "blind.txt").write_text(text, encoding="utf-8")
    (out / "spot-check.txt").write_text(spot, encoding="utf-8")
    (out / "mapping.sha256").write_text(digest + "\n", encoding="utf-8")
    (private / "mapping.json").write_text(
        json.dumps(mapping, ensure_ascii=False, sort_keys=True, indent=1), encoding="utf-8",
    )
    logger.info("annotation export %s: items=%d sha256=%s dir=%s", edition_date, len(mapping), digest, out)
    return out


def prepare_with_shadow(edition_date: date, *, now: datetime | None = None) -> int:
    """`DAILY_MODE=mas` 且 `DAILY_SHADOW_ENABLED=true` 的 06:00：P 影子先跑、M 後跑（手冊 2.3、8.3）。

    - 同一份快照：P 影子建快照（跨語言合併只跑一次），M 用 `plan_from_snapshot` 從同一份開始。
    - 額度：P 影子的每次嘗試記在 `SHADOW_PURPOSE`，上限 `DAILY_SHADOW_LLM_LIMIT`；M 至少保有其餘額度。
    - 影子失敗只記 log，M 照常（此時 M 自己建快照）；匯出失敗也只記 log。
    - 當天 daily_editions 已有這期（重跑、手動 prepare 過）就不跑影子，避免覆寫 M 用過的快照。
    """
    settings = get_settings()
    now = now or datetime.now(timezone.utc)
    snapshot = None
    with session_scope() as session:
        existing = session.scalar(select(DailyEdition.status).where(DailyEdition.edition_date == edition_date))
    if existing is not None:
        logger.info("pipeline shadow %s skipped: edition already %s", edition_date, existing)
    else:
        try:
            prepare_daily(edition_date, now=now, shadow=True)
            with session_scope() as session:
                row = session.scalar(select(DailySnapshot).where(DailySnapshot.edition_date == edition_date))
                snapshot = {"candidates": list(row.candidates)} if row is not None else None
        except Exception:  # noqa: BLE001 — 影子失敗不能影響 M
            logger.exception("pipeline shadow %s failed; MAS continues with its own snapshot", edition_date)
            snapshot = None
    edition_id = prepare_daily(edition_date, now=now, mode=MAS, snapshot=snapshot)
    if snapshot is not None:
        try:
            export_annotation(edition_date, getattr(settings, "daily_annotation_dir", "annotation"))
        except Exception:  # noqa: BLE001 — 匯出失敗不影響出刊
            logger.exception("annotation export %s failed", edition_date)
    return edition_id


async def _send(token: str, chat_id: int, text: str, html_path: Path, filename: str) -> list[int]:
    from telegram import Bot

    async with Bot(token=token) as bot:
        first = await bot.send_message(chat_id=chat_id, text=text, disable_web_page_preview=True)
        with html_path.open("rb") as fh:
            second = await bot.send_document(chat_id=chat_id, document=fh, filename=filename)
    return [first.message_id, second.message_id]


def publish_daily(edition_date: date, *, now: datetime | None = None) -> int:
    settings = get_settings()
    if not settings.telegram_bot_token or not settings.telegram_chat_id:
        raise DailyEditionError("TELEGRAM_BOT_TOKEN／TELEGRAM_CHAT_ID 未設定")
    mode = _mode(None)
    if mode == MAS:
        with session_scope() as session:
            edition = session.scalar(select(DailyEdition).where(DailyEdition.edition_date == edition_date))
            if edition is None:
                raise DailyEditionError("DAILY_MODE=mas 時沒有準備好的期數，發行不會重跑 prepare")
            edition_id = edition.id
    else:
        edition_id = prepare_daily(edition_date, now=now)
    registry = load_registry(settings.news_sources_path)
    with session_scope() as session:
        edition = session.get(DailyEdition, edition_id)
        if edition.status == "published":
            logger.info("daily edition %s already published; skip", edition_date)
            return edition_id
        if edition.status != "drafted":
            raise DailyEditionError(f"版次狀態 {edition.status}，不可發行（避免重複投遞）")
        edition.status = "publishing"
        view = _publication_view(session, edition, registry.sections, mode)
        text = telegram_digest(view)
        html_path = Path(edition.html_path) if edition.html_path else _write_edition_html(
            settings.daily_site_dir, edition_date, view,
        )
        html_path.write_text(render_html(view), encoding="utf-8")
        edition.html_path = str(html_path)
    try:
        message_ids = asyncio.run(
            _send(settings.telegram_bot_token, int(settings.telegram_chat_id), text, html_path,
                  f"AI綜合日報-{edition_date.isoformat()}.html")
        )
    except Exception:
        with session_scope() as session:
            session.get(DailyEdition, edition_id).status = "delivery_failed"
        logger.exception("daily edition %s delivery failed; marked delivery_failed", edition_date)
        raise
    with session_scope() as session:
        edition = session.get(DailyEdition, edition_id)
        edition.status = "published"
        edition.telegram_message_ids = message_ids
        edition.published_at = datetime.now(timezone.utc)
    logger.info("daily edition %s published: telegram=%s", edition_date, message_ids)
    return edition_id


def parse_now(text: str) -> datetime:
    """`--now` 的值：ISO 時間；沒帶時區就當成出刊時區（台北）。回傳 UTC aware。"""
    value = datetime.fromisoformat(text)
    if value.tzinfo is None:
        value = value.replace(tzinfo=ZoneInfo(get_settings().newsroom_delivery_timezone))
    return value.astimezone(timezone.utc)


def recluster(now: datetime) -> ClusterRunStats:
    """用同一個 `now` 增量聚合（重編舊期時，聚合時間窗要跟選題對齊）。"""
    registry = load_registry(get_settings().news_sources_path)
    with session_scope() as session:
        return cluster_recent_items(
            session,
            now=now,
            general_sources=registry.general_source_ids(),
            disabled_sources=registry.disabled_source_ids(),
        )


def _print_edition(edition_id: int) -> None:
    with session_scope() as session:
        edition = session.get(DailyEdition, edition_id)
        if edition is None:
            print(f"edition={edition_id}（影子版不寫 daily_editions）")
            return
        print(f"edition={edition.id} date={edition.edition_date} status={edition.status} "
              f"writer={edition.writer} html={edition.html_path}")
        print(edition.stats)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m reddit_tracker.daily")
    sub = parser.add_subparsers(dest="command", required=True)
    prepare = sub.add_parser("prepare", help="準備一期（不發送）")
    prepare.add_argument("--date", type=date.fromisoformat, default=None)
    prepare.add_argument("--writer", choices=LLM_PROVIDERS)
    prepare.add_argument("--refresh", action="store_true", help="重寫尚未發行的 draft")
    prepare.add_argument("--shadow", action="store_true", help="P 組影子版：寫 site/daily/shadow，不寫 daily_editions")
    prepare.add_argument("--mode", choices=(PIPELINE, MAS))
    prepare.add_argument(
        "--now", type=parse_now, default=None,
        help="把「現在」固定在這個時間（ISO；不帶時區＝台北），聚合、評分、選題、證據包都用它；重編舊期用",
    )
    prepare.add_argument("--recluster", action="store_true", help="準備前先用同一個 --now 聚合一輪")
    publish = sub.add_parser("publish", help="發行已準備的版次到 Telegram")
    publish.add_argument("--date", type=date.fromisoformat, default=None)
    trace = sub.add_parser("trace", help="印出一期的訊息與稿件版本")
    trace.add_argument("--date", type=date.fromisoformat, required=True)
    trace.add_argument("--variant", choices=(PIPELINE, MAS), default=MAS)
    trace.add_argument("--cluster", type=int, default=None)
    approve = sub.add_parser("approve", help="真人核准一則稿")
    approve.add_argument("--story", type=int, required=True)
    approve.add_argument("--by", required=True)
    hold = sub.add_parser("hold", help="真人 HOLD 一則稿")
    hold.add_argument("--story", type=int, required=True)
    hold.add_argument("--date", type=date.fromisoformat, required=True)
    hold.add_argument("--by", required=True)
    blind = sub.add_parser("blind-export", help="匯出盲計純文字與對照表雜湊")
    blind.add_argument("--dates", required=True, help="逗號分隔的 YYYY-MM-DD")
    blind.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    settings = get_settings()
    logging.basicConfig(level=settings.log_level, format="%(asctime)s %(levelname)s %(name)s | %(message)s")
    if args.command == "trace":
        from .mas.orchestrator import format_trace

        with session_scope() as session:
            print(format_trace(session, args.date, args.variant, args.cluster))
        return 0
    if args.command == "approve":
        with session_scope() as session:
            row = approve_story(session, args.story, by=args.by, now=datetime.now(timezone.utc))
            print(f"story={row.story_id} v{row.version} status={row.status} approved_by={row.approved_by}")
        return 0
    if args.command == "hold":
        from .mas.protocol import post_message

        with session_scope() as session:
            post_message(
                session, run_variant=MAS, edition_date=args.date, sender="human", recipient="eic",
                type="HOLD", now=datetime.now(timezone.utc), story_id=args.story,
                payload={"by": args.by, "detail": "審核者 HOLD"},
            )
            row = hold_story(session, args.story)
            print(f"story={row.story_id} v{row.version} status={row.status}")
        return 0
    if args.command == "blind-export":
        from .blind import export_blind_count

        days = [date.fromisoformat(part) for part in args.dates.split(",") if part]
        with session_scope() as session:
            text, mapping, digest = export_blind_count(session, days)
        args.out.mkdir(parents=True, exist_ok=True)
        (args.out / "blind.txt").write_text(text, encoding="utf-8")
        (args.out / "mapping.sha256").write_text(digest + "\n", encoding="utf-8")
        print(digest)
        print(f"items={len(mapping)}")
        return 0
    now = getattr(args, "now", None)
    if args.date:
        edition_date = args.date
    elif now is not None:
        edition_date = now.astimezone(ZoneInfo(settings.newsroom_delivery_timezone)).date()
    else:
        edition_date = _today()
    if args.command == "prepare":
        if args.recluster:
            print(recluster(now or datetime.now(timezone.utc)))
        edition_id = prepare_daily(
            edition_date, writer_mode=args.writer, refresh=args.refresh, mode=args.mode, shadow=args.shadow, now=now,
        )
    else:
        edition_id = publish_daily(edition_date)
    _print_edition(edition_id)
    return 0

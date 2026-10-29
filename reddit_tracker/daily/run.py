"""準備與發行綜合日報。

準備分三段：先在一個 session 讀資料、評分、選題、組證據；接著在任何 DB
交易之外呼叫 LLM（可能要幾分鐘，不能讓每 15 分鐘的收集等鎖）；最後
在另一個 session 一次寫入整期。發行只送已準備好的版次，且不重送。
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import shutil
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from sqlalchemy import select

from ..collection.entities import EntityContext, MergeRules, load_lexicon
from ..config import LLM_PROVIDERS, get_settings
from ..db import session_scope
from ..llm.quota import QuotaExhausted
from ..models import DailyArticle, DailyEdition, StoryCluster
from ..seeds.news_sources import SourceRegistry, load_registry
from .desk import DeskMerges, desk_merges
from .evidence import EvidenceItem, EvidencePack, build_evidence, title_context
from .market import fetch_market_box
from .render import render_html, telegram_digest
from .scoring import ScoredCluster, Selection, apply_merges, desk_pool, score_candidates, select_articles, window_start_for
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
    scored, desk = _editorial_meeting(session, scored, writer, registry.disabled_source_ids())
    context = title_context(session, now, load_lexicon(), registry.disabled_source_ids())
    planned = []
    for key, selection in enumerate(select_articles(scored), start=1):
        pack = story_evidence(session, selection.cluster, registry, context)
        if pack.items:
            planned.append(Planned(key, selection, pack.items, pack.notes))
    return EditionPlan(scored, candidate_count, desk.groups, planned, desk, context)


def prepare_daily(
    edition_date: date,
    *,
    writer_mode: str | None = None,
    refresh: bool = False,
    now: datetime | None = None,
    writer: DailyWriter | None = None,
) -> int:
    """冪等準備一期日報，回傳 edition id；不發送。

    `writer`：直接指定撰稿者（回歸集用 replay client），此時不看 `writer_mode`、不找 codex binary。
    """
    settings = get_settings()
    now = now or datetime.now(timezone.utc)
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
        if existing is not None:
            if existing.status in ("publishing", "published", "delivery_failed"):
                return existing.id
            if existing.status == "drafted" and not refresh:
                return existing.id
        if writer is None and writer_mode in LLM_WRITERS:
            writer = DailyWriter(writer_mode)
        plan = plan_edition(session, edition_date=edition_date, now=now, writer=writer, registry=registry)
        candidate_count, merged_groups, planned = plan.candidate_count, plan.merged_groups, plan.planned
        desk = plan.desk
    if not planned:
        raise DailyEditionError("沒有可刊登的事件；請確認收集與聚合是否正常")

    written = _write_all(planned, sections, writer)
    llm_requests = writer.requests if writer else 0
    market = fetch_market_box()

    with session_scope() as session:
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
        edition.status = "drafted"
        edition.writer = (writer.name if writer else "template") if ai_count == len(written) else (
            "template" if not ai_count else "mixed"
        )
        edition.stats = {
            "candidate_clusters": candidate_count,
            "merged_groups": merged_groups,
            # 合併來源拆開記：程式（譯名表＋共同實體）、LLM 原始回應、LLM 說合併但被程式剔除的
            "entity_merge_groups": desk.entity_groups if desk else [],
            "llm_merge_groups": desk.llm_groups if desk else [],
            "rejected_merges": desk.rejected if desk else [],
            "articles": len(written),
            "ai_articles": ai_count,
            "template_articles": len(written) - ai_count,
            "llm_requests": llm_requests,
            "sections": {k: sum(1 for p in planned if p.selection.section == k) for k in sections},
            "market": market,
        }
        edition.updated_at = now
        session.flush()
        path = Path(settings.daily_site_dir) / f"{edition_date.isoformat()}.html"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(render_html(edition, sections), encoding="utf-8")
        edition.html_path = str(path)
        logger.info(
            "daily edition %s drafted: articles=%d ai=%d template=%d",
            edition_date, len(written), ai_count, len(written) - ai_count,
        )
        return edition.id


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
        text = telegram_digest(edition, registry.sections)
        html_path = Path(edition.html_path)
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m reddit_tracker.daily")
    sub = parser.add_subparsers(dest="command", required=True)
    prepare = sub.add_parser("prepare", help="準備一期（不發送）")
    prepare.add_argument("--date", type=date.fromisoformat, default=None)
    prepare.add_argument("--writer", choices=LLM_PROVIDERS)
    prepare.add_argument("--refresh", action="store_true", help="重寫尚未發行的 draft")
    publish = sub.add_parser("publish", help="發行已準備的版次到 Telegram")
    publish.add_argument("--date", type=date.fromisoformat, default=None)
    args = parser.parse_args(argv)
    settings = get_settings()
    logging.basicConfig(level=settings.log_level, format="%(asctime)s %(levelname)s %(name)s | %(message)s")
    edition_date = args.date or _today()
    if args.command == "prepare":
        edition_id = prepare_daily(edition_date, writer_mode=args.writer, refresh=args.refresh)
    else:
        edition_id = publish_daily(edition_date)
    with session_scope() as session:
        edition = session.get(DailyEdition, edition_id)
        print(f"edition={edition.id} date={edition.edition_date} status={edition.status} "
              f"writer={edition.writer} html={edition.html_path}")
        print(edition.stats)
    return 0

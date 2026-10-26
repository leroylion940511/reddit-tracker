"""準備與發行綜合日報。

準備分三段：先在一個 session 讀資料、評分、選題、組證據；接著在任何 DB
交易之外呼叫 Gemini（可能要幾分鐘，不能讓每 15 分鐘的收集等鎖）；最後
在另一個 session 一次寫入整期。發行只送已準備好的版次，且不重送。
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import time
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from sqlalchemy import select

from ..config import get_settings
from ..db import session_scope
from ..models import DailyArticle, DailyEdition, StoryCluster
from ..seeds.news_sources import load_registry
from .evidence import EvidenceItem, build_evidence
from .market import fetch_market_box
from .render import render_html, telegram_digest
from .scoring import Selection, apply_merges, desk_pool, score_candidates, select_articles, window_start_for
from .writer import GeminiDailyWriter, WrittenStory, review_story, template_story

logger = logging.getLogger(__name__)

FRONT_GROUP = "front"
WRITE_ATTEMPTS = 3
RETRY_DELAY_SECONDS = 15.0


class DailyEditionError(RuntimeError):
    pass


@dataclass
class _Planned:
    key: int
    selection: Selection
    evidence: list[EvidenceItem]


def _today() -> date:
    return datetime.now(ZoneInfo(get_settings().newsroom_delivery_timezone)).date()


def _editorial_meeting(session, scored, writer: GeminiDailyWriter | None) -> tuple[list, list[list[int]]]:
    """用一次 LLM 請求找出跨語言的同一事件並合併；失敗就照原樣繼續。"""
    if writer is None:
        return scored, []
    pool = desk_pool(scored)
    titles = dict(
        session.execute(
            select(StoryCluster.id, StoryCluster.title).where(StoryCluster.id.in_([s.cluster_id for s in pool]))
        ).all()
    )
    try:
        groups = writer.find_same_events([(s.cluster_id, titles.get(s.cluster_id) or "") for s in pool])
    except Exception as exc:  # noqa: BLE001 — 編輯會議失敗不擋出刊，只是可能重複
        logger.warning("editorial meeting failed: %s", exc)
        return scored, []
    return apply_merges(scored, groups), groups


def _write_all(
    planned: list[_Planned], sections: dict[str, str], writer: GeminiDailyWriter | None
) -> dict[int, WrittenStory]:
    groups: dict[str, list[_Planned]] = {}
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
                    failure = f"Gemini 撰稿失敗（{attempt} 次）：{type(exc).__name__}: {str(exc)[:160]}"
                    logger.warning("daily writer failed for %s: %s", group, failure)
                    if attempt < WRITE_ATTEMPTS:
                        time.sleep(RETRY_DELAY_SECONDS)
        for p in items:
            story = generated.get(p.key)
            notes = [failure] if failure else []
            if story is not None:
                problems = review_story(story, p.evidence)
                if problems:
                    notes += problems
                    story = None
            elif writer is not None and not failure:
                notes.append("Gemini 回應缺少這則")
            if story is None:
                story = template_story(p.evidence, p.selection.cluster.kind)
            story.review_notes = notes
            written[p.key] = story
    return written


def prepare_daily(
    edition_date: date, *, writer_mode: str | None = None, refresh: bool = False, now: datetime | None = None
) -> int:
    """冪等準備一期日報，回傳 edition id；不發送。"""
    settings = get_settings()
    now = now or datetime.now(timezone.utc)
    writer_mode = writer_mode or settings.daily_writer
    if writer_mode == "gemini" and not settings.gemini_api_key:
        writer_mode = "template"
    registry = load_registry(settings.news_sources_path)
    sections = registry.sections
    source_names = {s.id: s.name for s in registry.sources}

    with session_scope() as session:
        existing = session.scalar(select(DailyEdition).where(DailyEdition.edition_date == edition_date))
        if existing is not None:
            if existing.status in ("publishing", "published", "delivery_failed"):
                return existing.id
            if existing.status == "drafted" and not refresh:
                return existing.id
        writer = GeminiDailyWriter() if writer_mode == "gemini" else None
        scored = score_candidates(
            session, edition_date=edition_date, now=now, general_sources=registry.general_source_ids()
        )
        candidate_count = len(scored)
        scored, merged_groups = _editorial_meeting(session, scored, writer)
        planned = []
        for key, selection in enumerate(select_articles(scored), start=1):
            evidence = build_evidence(session, selection.cluster.all_ids, source_names)
            if evidence:
                planned.append(_Planned(key, selection, evidence))
    if not planned:
        raise DailyEditionError("沒有可刊登的事件；請確認收集與聚合是否正常")

    written = _write_all(planned, sections, writer)
    gemini_requests = writer.requests if writer else 0
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
        gemini_count = sum(1 for s in written.values() if s.writer == "gemini")
        edition.status = "drafted"
        edition.writer = "gemini" if gemini_count == len(written) else ("template" if not gemini_count else "mixed")
        edition.stats = {
            "candidate_clusters": candidate_count,
            "merged_groups": merged_groups,
            "articles": len(written),
            "gemini_articles": gemini_count,
            "template_articles": len(written) - gemini_count,
            "gemini_requests": gemini_requests,
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
            "daily edition %s drafted: articles=%d gemini=%d template=%d",
            edition_date, len(written), gemini_count, len(written) - gemini_count,
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
    prepare.add_argument("--writer", choices=("gemini", "template"))
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

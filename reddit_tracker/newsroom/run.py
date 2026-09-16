"""Prepare and publish the v5 AI newsroom's daily trial edition.

The command defaults to a non-sending preview.  The scheduler is the only
normal caller that passes ``send=True`` at the configured delivery time.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
from dataclasses import dataclass
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import select

from ..config import get_settings
from ..db import session_scope
from ..models import NewsroomEdition, ReaderProfile
from .gemini_writer import GeminiNewsroomWriter
from .planning import previous_calendar_day_window, plan_edition
from .publisher import format_telegram_messages, send_telegram_messages
from .rendering import EditionView, load_edition_view, render_html
from .repository import create_reader_profile, get_or_create_edition
from .writing import NewsroomWritingError, TemplateDraftingAgent, draft_edition

logger = logging.getLogger(__name__)

DEFAULT_READER_PROMPT = "多看台灣生活、人際情感、職場與有趣的網路日常；少看政治攻防。"
DEFAULT_TOPICS = ["relationships", "daily_life", "internet_culture", "taiwan_life", "human_interest"]


@dataclass(frozen=True)
class PreparedEdition:
    edition_id: int
    chat_id: int
    view: EditionView
    writer_used: str


def _trial_reader(session) -> ReaderProfile:
    settings = get_settings()
    if not settings.telegram_chat_id:
        raise RuntimeError("TELEGRAM_CHAT_ID 未設定，無法建立試刊讀者")
    try:
        chat_id = int(settings.telegram_chat_id)
    except ValueError as exc:
        raise RuntimeError("TELEGRAM_CHAT_ID 必須是整數 chat id") from exc
    profile = session.scalar(select(ReaderProfile).where(ReaderProfile.telegram_chat_id == chat_id))
    if profile is not None:
        return profile
    return create_reader_profile(
        session,
        telegram_chat_id=chat_id,
        preference_prompt=DEFAULT_READER_PROMPT,
        included_topics=DEFAULT_TOPICS,
        timezone_name=settings.newsroom_delivery_timezone,
        delivery_time=f"{settings.newsroom_delivery_hour:02d}:{settings.newsroom_delivery_minute:02d}",
    )


def prepare_edition(*, edition_date: date, writer_mode: str | None = None) -> PreparedEdition:
    """Idempotently create or load one trial edition; never sends Telegram."""
    settings = get_settings()
    chosen_writer = writer_mode or settings.newsroom_writer
    with session_scope() as session:
        reader = _trial_reader(session)
        window = previous_calendar_day_window(edition_date, timezone_name=reader.timezone)
        edition = get_or_create_edition(
            session,
            reader=reader,
            edition_date=edition_date,
            window_start=window.start_utc,
            window_end=window.end_utc,
        ).edition
        existing_view = load_edition_view(session, edition=edition)
        if not existing_view.items:
            planning = plan_edition(session, edition=edition)
            writer_used = chosen_writer
            try:
                if chosen_writer == "gemini":
                    draft_edition(
                        session,
                        edition=edition,
                        plan=planning.plan,
                        drafting_agent=GeminiNewsroomWriter(),
                    )
                elif chosen_writer == "template":
                    draft_edition(session, edition=edition, plan=planning.plan)
                else:
                    raise RuntimeError(f"unknown newsroom writer: {chosen_writer}")
            except NewsroomWritingError:
                if chosen_writer != "gemini" or not settings.newsroom_template_fallback:
                    raise
                logger.exception("Gemini writing failed; using source-transparent template fallback")
                draft_edition(
                    session,
                    edition=edition,
                    plan=planning.plan,
                    drafting_agent=TemplateDraftingAgent(),
                )
                writer_used = "template_fallback"
        else:
            writer_used = "existing_draft"
        view = load_edition_view(session, edition=edition)
        if not view.items:
            raise RuntimeError("edition was prepared without any items")
        if reader.telegram_chat_id is None:
            raise RuntimeError("trial reader has no Telegram chat id")
        return PreparedEdition(
            edition_id=edition.id,
            chat_id=reader.telegram_chat_id,
            view=view,
            writer_used=writer_used,
        )


def publish_edition(*, edition_date: date) -> PreparedEdition:
    """Claim a drafted edition, send it once, and persist delivery evidence."""
    settings = get_settings()
    if not settings.telegram_bot_token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN 未設定，無法發行試刊")
    prepared = prepare_edition(edition_date=edition_date)
    with session_scope() as session:
        edition = session.get(NewsroomEdition, prepared.edition_id)
        if edition is None:
            raise RuntimeError("prepared edition disappeared")
        if edition.status == "published":
            logger.info("edition %s already published; no duplicate Telegram send", edition.id)
            return prepared
        if edition.status == "publishing":
            raise RuntimeError("edition is already publishing; refusing a possible duplicate Telegram send")
        if edition.status != "drafted":
            raise RuntimeError(f"edition is not publishable: {edition.status}")
        edition.status = "publishing"

    messages = format_telegram_messages(prepared.view)
    try:
        message_ids = asyncio.run(send_telegram_messages(
            token=settings.telegram_bot_token,
            chat_id=prepared.chat_id,
            messages=messages,
        ))
    except Exception:
        with session_scope() as session:
            edition = session.get(NewsroomEdition, prepared.edition_id)
            if edition is not None and edition.status == "publishing":
                edition.status = "drafted"
        raise
    with session_scope() as session:
        edition = session.get(NewsroomEdition, prepared.edition_id)
        if edition is None:
            raise RuntimeError("prepared edition disappeared after delivery")
        edition.status = "published"
        edition.telegram_message_id = message_ids[0]
        edition.published_at = datetime.now(timezone.utc)
    logger.info("published newsroom edition=%s telegram_messages=%d", prepared.edition_id, len(message_ids))
    return prepared


def _today_in_delivery_timezone() -> date:
    return datetime.now(ZoneInfo(get_settings().newsroom_delivery_timezone)).date()


def main() -> int:
    parser = argparse.ArgumentParser(description="Prepare or publish the AI newsroom daily edition")
    parser.add_argument("--date", type=date.fromisoformat, default=_today_in_delivery_timezone())
    parser.add_argument("--writer", choices=("gemini", "template"))
    parser.add_argument("--preview", action="store_true", help="print a preview; this is the default")
    parser.add_argument("--send", action="store_true", help="send a prepared edition to Telegram")
    parser.add_argument("--html", help="optional local HTML preview path")
    args = parser.parse_args()
    if args.send:
        prepared = publish_edition(edition_date=args.date)
        print(f"published edition={prepared.edition_id} items={len(prepared.view.items)}")
    else:
        prepared = prepare_edition(edition_date=args.date, writer_mode=args.writer)
        print(f"preview edition={prepared.edition_id} items={len(prepared.view.items)} writer={prepared.writer_used}")
        for message in format_telegram_messages(prepared.view, preview=True):
            print("\n--- Telegram preview ---\n" + message)
    if args.html:
        from pathlib import Path
        Path(args.html).write_text(render_html(prepared.view), encoding="utf-8")
        print(f"html={args.html}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())


__all__ = ["PreparedEdition", "prepare_edition", "publish_edition"]

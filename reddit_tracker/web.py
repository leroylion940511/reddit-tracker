"""本機 Reddit Tracker 控制台。

只綁定 127.0.0.1；提供服務 lifecycle、非敏感設定、SQLite 資料與 QA
對話紀錄的同一個操作介面。所有 launchctl 呼叫使用固定參數，避免 UI
變成任意 shell 執行入口。
"""

from __future__ import annotations

import json
import os
import plistlib
import shutil
import subprocess
import sys
import time
import webbrowser
from collections.abc import Iterator
from dataclasses import asdict
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any, Literal
from zoneinfo import ZoneInfo

import uvicorn
from fastapi import FastAPI, HTTPException, Query
from fastapi.encoders import jsonable_encoder
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import func, inspect, select, text

from .config import Settings, get_settings
from .db import session_scope
from .models import (
    CandidatePost,
    DailyPush,
    Feedback,
    LLMRecord,
    EditionItem,
    EditionItemSource,
    NewsroomEdition,
    QAMessage,
    QASession,
    RelatedPost,
    ReaderProfile,
    ReaderFeedback,
    ScoringRecord,
    SubredditSource,
    TrackedPost,
)
from .newsroom.rendering import load_edition_view
from .newsroom.repository import record_reader_feedback

PROJECT_ROOT = Path(__file__).resolve().parents[1]
STATIC_ROOT = Path(__file__).resolve().parent / "static"
ENV_PATH = PROJECT_ROOT / ".env"
LOG_PATHS = {
    "scheduler": PROJECT_ROOT / "scheduler.log",
    "bot": PROJECT_ROOT / "bot.log",
    "newsroom": PROJECT_ROOT / "newsroom.log",
}
SERVICE_LABELS = (
    "com.leroy.reddit-tracker.scheduler",
    "com.leroy.reddit-tracker.bot",
    "com.leroy.reddit-tracker.newsroom",
)
PLIST_SOURCES = {
    label: PROJECT_ROOT / "deploy" / f"{label}.plist" for label in SERVICE_LABELS
}
PLIST_DESTINATIONS = {
    label: Path.home() / "Library" / "LaunchAgents" / f"{label}.plist"
    for label in SERVICE_LABELS
}

# 只允許調整不含憑證的操作性設定。金鑰只顯示是否已設定，不能經由前端讀寫。
EDITABLE_SETTINGS: dict[str, tuple[type[str | int | float], Any]] = {
    "reddit_scraper": (str, {"public_json", "praw", "fake"}),
    "llm_provider": (str, {"web", "minimax", "gemini", "anthropic", "fake"}),
    "gemini_scoring_model": (str, {"gemini-3.5-flash-lite", "gemini-3.1-flash-lite", "gemini-2.5-flash-lite"}),
    "gemini_qa_model": (str, {"gemini-3.5-flash", "gemini-2.5-flash", "gemini-2.5-flash-lite"}),
    "gemini_scoring_daily_limit": (int, (1, 5000)),
    "gemini_qa_daily_limit": (int, (1, 1000)),
    "gemini_requests_per_minute": (int, (1, 60)),
    "gemini_fallback_provider": (str, {"web", "fake"}),
    "web_llm_provider": (str, {"chatgpt", "gemini"}),
    "web_llm_cdp_url": (str, None),
    "web_llm_timeout_seconds": (float, (10.0, 600.0)),
    "newsroom_writer": (str, {"gemini", "template"}),
    "newsroom_preparation_hour": (int, (0, 23)),
    "newsroom_preparation_minute": (int, (0, 59)),
    "newsroom_discovery_interval_minutes": (int, (5, 1440)),
    "poll_subreddit_minutes": (int, (5, 1440)),
    "poll_keyword_hours": (int, (1, 168)),
    "scoring_minutes": (int, (5, 1440)),
    "scoring_batch_limit": (int, (1, 200)),
    "polling_minutes": (int, (5, 1440)),
    "detection_minutes": (int, (5, 1440)),
    "log_level": (str, {"DEBUG", "INFO", "WARNING", "ERROR"}),
}


class SettingsUpdate(BaseModel):
    values: dict[str, str | int | float | None] = Field(default_factory=dict)


class ServiceAction(BaseModel):
    service: Literal["scheduler", "bot", "newsroom"] = "newsroom"


class NewsroomFeedbackAction(BaseModel):
    action: Literal["more", "less", "follow"]


class NewsroomReaderProfileUpdate(BaseModel):
    preference_prompt: str = Field(min_length=1, max_length=500)
    included_topics: list[str] = Field(default_factory=list, max_length=20)
    excluded_topics: list[str] = Field(default_factory=list, max_length=20)
    included_subreddits: list[str] = Field(default_factory=list, max_length=50)
    excluded_subreddits: list[str] = Field(default_factory=list, max_length=50)
    included_keywords: list[str] = Field(default_factory=list, max_length=30)
    excluded_keywords: list[str] = Field(default_factory=list, max_length=30)


def _run(command: list[str], *, timeout: float = 12.0) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, text=True, capture_output=True, timeout=timeout, check=False)


def _label_for(service: str) -> str:
    label = f"com.leroy.reddit-tracker.{service}"
    if label not in SERVICE_LABELS:
        raise HTTPException(status_code=400, detail="未知的服務名稱")
    return label


def _labels(action: ServiceAction) -> tuple[str, ...]:
    return (_label_for(action.service),)


def _service_status(label: str) -> dict[str, Any]:
    uid = str(os.getuid())
    target = f"gui/{uid}/{label}"
    printed = _run(["launchctl", "print", target])
    disabled = _run(["launchctl", "print-disabled", f"gui/{uid}"])
    # macOS launchctl prints symbolic values (``=> disabled``), while older
    # fixture/output variants may use booleans.  Accept both so the dashboard
    # does not tell users that a deliberately disabled legacy service is only
    # "not loaded".
    disabled_flag = (
        f'"{label}" => disabled' in disabled.stdout
        or f'"{label}" => true' in disabled.stdout
    )
    status = {
        "label": label,
        "name": {
            "scheduler": "v4 排程器",
            "bot": "v4 Telegram Bot",
            "newsroom": "AI 新聞室",
        }[label.rsplit(".", maxsplit=1)[-1]],
        "running": printed.returncode == 0,
        "disabled": disabled_flag,
        "plist_installed": PLIST_DESTINATIONS[label].exists(),
        "detail": (printed.stderr or printed.stdout).strip()[-300:],
    }
    if label.endswith(".newsroom"):
        status.update(_newsroom_schema_status())
    return status


def _newsroom_schema_status() -> dict[str, Any]:
    """Expose only schema readiness, never database contents or credentials."""
    try:
        config = Config(str(PROJECT_ROOT / "alembic.ini"))
        expected = ScriptDirectory.from_config(config).get_current_head()
        with session_scope() as session:
            actual = session.execute(text("SELECT version_num FROM alembic_version")).scalar_one_or_none()
    except Exception as exc:  # noqa: BLE001 - dashboard must keep service status readable
        return {"schema_ready": False, "schema_detail": f"無法確認 migration：{exc}"}
    if actual == expected:
        return {"schema_ready": True, "schema_detail": "資料庫 schema 已是最新版本。"}
    return {
        "schema_ready": False,
        "schema_detail": "資料庫 schema 尚未升級；請先執行 newsroom-deploy。",
    }


def service_statuses() -> list[dict[str, Any]]:
    return [_service_status(label) for label in SERVICE_LABELS]


def _ensure_plist(label: str) -> Path:
    destination = PLIST_DESTINATIONS[label]
    source = PLIST_SOURCES[label]
    if destination.exists():
        return destination
    if not source.exists():
        raise RuntimeError(f"找不到服務設定檔：{source.name}")
    # Validate the tracked plist before copying it into the user's LaunchAgents directory.
    with source.open("rb") as stream:
        plistlib.load(stream)
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    return destination


def _start_service(label: str) -> dict[str, str]:
    status = _service_status(label)
    if status["running"]:
        return {"label": label, "result": "already_running"}
    if label.endswith(".newsroom") and not status.get("schema_ready", False):
        raise RuntimeError("新聞室資料庫尚未升級；請先執行 deploy/install_launchd.sh newsroom-deploy")
    uid = str(os.getuid())
    plist = _ensure_plist(label)
    enable = _run(["launchctl", "enable", f"gui/{uid}/{label}"])
    if enable.returncode != 0:
        raise RuntimeError(enable.stderr.strip() or "無法啟用服務")
    boot = _run(["launchctl", "bootstrap", f"gui/{uid}", str(plist)])
    if boot.returncode != 0:
        raise RuntimeError(boot.stderr.strip() or "無法啟動服務")
    return {"label": label, "result": "started"}


def _stop_service(label: str) -> dict[str, str]:
    uid = str(os.getuid())
    target = f"gui/{uid}/{label}"
    bootout = _run(["launchctl", "bootout", target])
    # bootout 回傳非 0 代表原本未載入；仍繼續 disable，確保登入後不會復活。
    disable = _run(["launchctl", "disable", target])
    if disable.returncode != 0:
        raise RuntimeError(disable.stderr.strip() or "無法停用服務")
    return {
        "label": label,
        "result": "stopped" if bootout.returncode == 0 else "already_stopped",
    }


def _tail(path: Path, lines: int = 180) -> str:
    if not path.exists():
        return "尚無日誌檔。"
    with path.open("rb") as stream:
        stream.seek(0, os.SEEK_END)
        size = stream.tell()
        stream.seek(max(0, size - 96_000))
        text = stream.read().decode("utf-8", errors="replace")
    return "\n".join(text.splitlines()[-lines:])


def _env_lines() -> Iterator[tuple[str | None, str]]:
    if not ENV_PATH.exists():
        return iter(())
    pairs: list[tuple[str | None, str]] = []
    for raw_line in ENV_PATH.read_text(encoding="utf-8").splitlines():
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#") or "=" not in raw_line:
            pairs.append((None, raw_line))
            continue
        key, _value = raw_line.split("=", 1)
        pairs.append((key.strip(), raw_line))
    return iter(pairs)


def _env_value(value: str | int | float) -> str:
    text = str(value)
    return json.dumps(text, ensure_ascii=False) if any(ch.isspace() for ch in text) else text


def _validate_setting(key: str, raw: str | int | float | None) -> str:
    spec = EDITABLE_SETTINGS.get(key)
    if spec is None or raw is None:
        raise ValueError(f"不允許修改設定：{key}")
    expected, rule = spec
    if expected is int:
        if isinstance(raw, bool):
            raise ValueError(f"{key} 必須是整數")
        value: str | int | float = int(raw)
    elif expected is float:
        if isinstance(raw, bool):
            raise ValueError(f"{key} 必須是數字")
        value = float(raw)
    else:
        value = str(raw).strip()
    if key == "web_llm_cdp_url" and not value.startswith("http://127.0.0.1:"):
        raise ValueError("Chrome DevTools 位址只能使用 127.0.0.1")
    if isinstance(rule, set) and value not in rule:
        raise ValueError(f"{key} 的值不支援")
    if isinstance(rule, tuple) and not (rule[0] <= value <= rule[1]):
        raise ValueError(f"{key} 必須介於 {rule[0]} 到 {rule[1]}")
    return _env_value(value)


def update_env(values: dict[str, str | int | float | None]) -> None:
    validated = {key.upper(): _validate_setting(key, value) for key, value in values.items()}
    original = list(_env_lines())
    seen: set[str] = set()
    result: list[str] = []
    for key, line in original:
        if key is None:
            result.append(line)
        elif key.upper() in validated:
            result.append(f"{key.upper()}={validated[key.upper()]}")
            seen.add(key.upper())
        else:
            result.append(line)
    for key, value in validated.items():
        if key not in seen:
            result.append(f"{key}={value}")
    ENV_PATH.write_text("\n".join(result).rstrip() + "\n", encoding="utf-8")
    get_settings.cache_clear()


def _settings_payload() -> dict[str, Any]:
    settings = Settings()
    values = {key: getattr(settings, key) for key in EDITABLE_SETTINGS}
    return {
        "values": values,
        "secrets": {
            "telegram_ready": bool(settings.telegram_bot_token and settings.telegram_chat_id),
            "anthropic_key_set": bool(settings.anthropic_api_key),
            "minimax_key_set": bool(settings.minimax_api_key),
            "gemini_key_set": bool(settings.gemini_api_key),
        },
        "restart_hint": "設定已寫入 .env；已執行的背景服務請重新啟動後才會套用。",
    }


def _overview() -> dict[str, Any]:
    with session_scope() as session:
        counts = {
            "candidates": session.scalar(select(func.count()).select_from(CandidatePost)) or 0,
            "tracked_active": session.scalar(
                select(func.count()).select_from(TrackedPost).where(TrackedPost.status == "active")
            ) or 0,
            "qa_sessions": session.scalar(select(func.count()).select_from(QASession)) or 0,
            "qa_messages": session.scalar(select(func.count()).select_from(QAMessage)) or 0,
            "related_events": session.scalar(select(func.count()).select_from(RelatedPost)) or 0,
            "newsroom_editions": session.scalar(select(func.count()).select_from(NewsroomEdition)) or 0,
            "newsroom_published": session.scalar(
                select(func.count()).select_from(NewsroomEdition).where(NewsroomEdition.status == "published")
            ) or 0,
        }
        latest = {
            "candidate": session.scalar(select(func.max(CandidatePost.discovered_at))),
            "qa": session.scalar(select(func.max(QAMessage.sent_at))),
            "llm": session.scalar(select(func.max(LLMRecord.called_at))),
            "edition": session.scalar(select(func.max(NewsroomEdition.edition_date))),
        }
        llm_cost = session.scalar(select(func.coalesce(func.sum(LLMRecord.cost_usd), 0)))
    return jsonable_encoder({"counts": counts, "latest": latest, "llm_cost_usd": llm_cost, "services": service_statuses()})


def _rows(kind: str, limit: int) -> list[dict[str, Any]]:
    statements: dict[str, Any] = {
        "candidates": select(CandidatePost).order_by(CandidatePost.discovered_at.desc()),
        "tracked": select(TrackedPost).order_by(TrackedPost.promoted_at.desc()),
        "scoring": select(ScoringRecord).order_by(ScoringRecord.scored_at.desc()),
        "pushes": select(DailyPush).order_by(DailyPush.push_date.desc(), DailyPush.rank.asc()),
        "feedback": select(Feedback).order_by(Feedback.acted_at.desc()),
        "related": select(RelatedPost).order_by(RelatedPost.discovered_at.desc()),
        "llm": select(LLMRecord).order_by(LLMRecord.called_at.desc()),
    }
    statement = statements.get(kind)
    if statement is None:
        raise HTTPException(status_code=400, detail="未知的資料表")
    with session_scope() as session:
        records = session.scalars(statement.limit(limit)).all()
        return [
            jsonable_encoder(
                {
                    property_.columns[0].name: getattr(record, property_.key)
                    for property_ in inspect(record).mapper.column_attrs
                }
            )
            for record in records
        ]


def _qa_sessions(limit: int) -> list[dict[str, Any]]:
    with session_scope() as session:
        rows = session.execute(
            select(QASession, TrackedPost, CandidatePost)
            .join(TrackedPost, QASession.tracked_post_id == TrackedPost.id)
            .join(CandidatePost, TrackedPost.candidate_post_id == CandidatePost.id)
            .order_by(QASession.started_at.desc())
            .limit(limit)
        ).all()
    return jsonable_encoder([
        {
            "id": qa.id,
            "user_id": qa.user_id,
            "state": qa.state,
            "started_at": qa.started_at,
            "ended_at": qa.ended_at,
            "tracked_post_id": tracked.id,
            "title": candidate.title,
            "subreddit": candidate.subreddit,
        }
        for qa, tracked, candidate in rows
    ])


def _newsroom_editions(limit: int) -> list[dict[str, Any]]:
    with session_scope() as session:
        rows = session.execute(
            select(NewsroomEdition, func.count(EditionItem.id))
            .outerjoin(EditionItem, EditionItem.edition_id == NewsroomEdition.id)
            .group_by(NewsroomEdition.id)
            .order_by(NewsroomEdition.edition_date.desc(), NewsroomEdition.id.desc())
            .limit(limit)
        ).all()
    return jsonable_encoder([
        {
            "id": edition.id,
            "edition_date": edition.edition_date,
            "status": edition.status,
            "item_count": item_count,
            "published_at": edition.published_at,
            "editor_summary": edition.editor_summary,
        }
        for edition, item_count in rows
    ])


def _newsroom_edition(edition_id: int) -> dict[str, Any]:
    with session_scope() as session:
        edition = session.get(NewsroomEdition, edition_id)
        if edition is None:
            raise HTTPException(status_code=404, detail="找不到此新聞版次")
        view = load_edition_view(session, edition=edition)
        payload = {
            "id": edition.id,
            "edition_date": edition.edition_date,
            "status": edition.status,
            "published_at": edition.published_at,
            "editor_summary": edition.editor_summary,
            "view": asdict(view),
        }
    return jsonable_encoder(payload)


def _newsroom_pilot(*, now: datetime | None = None) -> dict[str, Any]:
    """Report the immutable pilot gate alongside the rolling seven-day view.

    The pilot is a one-time launch criterion.  It must remain passed after the
    first successful seven-day run rolls outside the dashboard's current
    seven-day observation window.
    """
    with session_scope() as session:
        reader = _active_reader_profile(session)
        current_time = now or datetime.now(ZoneInfo(reader.timezone))
        today = current_time.astimezone(ZoneInfo(reader.timezone)).date()
        first_day = today - timedelta(days=6)
        editions = list(session.scalars(
            select(NewsroomEdition)
            .where(
                NewsroomEdition.reader_profile_id == reader.id,
                NewsroomEdition.edition_date <= today,
            )
            .order_by(NewsroomEdition.edition_date.asc())
        ).all())
        edition_by_day = {edition.edition_date: edition for edition in editions}
        items = list(session.scalars(
            select(EditionItem).where(EditionItem.edition_id.in_([edition.id for edition in editions] or [-1]))
        ).all())
        items_by_edition: dict[int, list[EditionItem]] = {}
        for item in items:
            items_by_edition.setdefault(item.edition_id, []).append(item)
        sourced_item_ids = set(session.scalars(
            select(EditionItemSource.edition_item_id).where(
                EditionItemSource.edition_item_id.in_([item.id for item in items] or [-1])
            )
        ).all())
        feedback_rows = session.execute(
            select(EditionItem.edition_id, ReaderFeedback.action, func.count(ReaderFeedback.id))
            .join(ReaderFeedback, ReaderFeedback.edition_item_id == EditionItem.id)
            .where(EditionItem.edition_id.in_([edition.id for edition in editions] or [-1]))
            .group_by(EditionItem.edition_id, ReaderFeedback.action)
        ).all()
    feedback_by_edition: dict[int, dict[str, int]] = {}
    for edition_id, action, count in feedback_rows:
        feedback_by_edition.setdefault(edition_id, {})[action] = int(count)
    days = []
    for offset in range(7):
        day = first_day + timedelta(days=offset)
        edition = edition_by_day.get(day)
        day_items = items_by_edition.get(edition.id, []) if edition else []
        feedback = feedback_by_edition.get(edition.id, {}) if edition else {}
        days.append({
            "date": day,
            "status": edition.status if edition else "missing",
            "item_count": len(day_items),
            "layout_valid": 8 <= len(day_items) <= 10,
            "sources_complete": bool(day_items) and all(item.id in sourced_item_ids for item in day_items),
            "positive_feedback": feedback.get("more", 0),
            "feedback_total": sum(feedback.values()),
        })
    published_days = sum(day["status"] == "published" for day in days)
    source_complete_days = sum(day["sources_complete"] for day in days)
    gate_window: dict[str, date] | None = None
    if edition_by_day:
        earliest_day = min(edition_by_day)
        latest_start = today - timedelta(days=6)
        candidate_start = earliest_day
        while candidate_start <= latest_start:
            candidate_days = [
                edition_by_day.get(candidate_start + timedelta(days=offset))
                for offset in range(7)
            ]
            if all(
                edition is not None
                and edition.status == "published"
                and 8 <= len(items_by_edition.get(edition.id, [])) <= 10
                and all(
                    item.id in sourced_item_ids
                    for item in items_by_edition.get(edition.id, [])
                )
                for edition in candidate_days
            ):
                gate_window = {
                    "start_date": candidate_start,
                    "end_date": candidate_start + timedelta(days=6),
                }
                break
            candidate_start += timedelta(days=1)
    current_window_complete = all(
        day["status"] == "published" and day["layout_valid"] and day["sources_complete"]
        for day in days
    )
    return jsonable_encoder({
        "days": days,
        "published_days": published_days,
        "source_complete_days": source_complete_days,
        # Keep this established field as the durable launch-gate result for
        # existing dashboard clients.  The rolling state is exposed separately.
        "pilot_complete": gate_window is not None,
        "gate_passed_window": gate_window,
        "current_window_complete": current_window_complete,
    })


def _as_utc(value: datetime) -> datetime:
    """SQLite may return a naive timestamp even for timezone-aware columns."""
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _newsroom_source_health() -> dict[str, Any]:
    """Expose candidate-source freshness without exposing scraper credentials."""
    settings = get_settings()
    now = datetime.now(UTC)
    recent_cutoff = now - timedelta(hours=24)
    freshness_limit = timedelta(minutes=settings.newsroom_discovery_interval_minutes * 2 + 5)
    with session_scope() as session:
        sources = list(session.scalars(
            select(SubredditSource)
            .where(SubredditSource.enabled.is_(True))
            .order_by(SubredditSource.name.asc())
        ).all())
        rows = []
        for source in sources:
            source_key = source.name.lower()
            latest_candidate_at = session.scalar(
                select(func.max(CandidatePost.discovered_at)).where(
                    func.lower(CandidatePost.subreddit) == source_key
                )
            )
            recent_candidates = session.scalar(
                select(func.count())
                .select_from(CandidatePost)
                .where(
                    func.lower(CandidatePost.subreddit) == source_key,
                    CandidatePost.discovered_at >= recent_cutoff,
                )
            ) or 0
            if source.last_polled_at is None:
                poll_state = "never"
            elif now - _as_utc(source.last_polled_at) <= freshness_limit:
                poll_state = "current"
            else:
                poll_state = "stale"
            rows.append({
                "name": source.name,
                "lang_hint": source.lang_hint,
                "last_polled_at": source.last_polled_at,
                "latest_candidate_at": latest_candidate_at,
                "recent_candidate_count": int(recent_candidates),
                "poll_state": poll_state,
            })
    return jsonable_encoder({
        "poll_interval_minutes": settings.newsroom_discovery_interval_minutes,
        "enabled_source_count": len(rows),
        "current_source_count": sum(row["poll_state"] == "current" for row in rows),
        "recent_candidate_count": sum(row["recent_candidate_count"] for row in rows),
        "sources": rows,
    })


def _active_reader_profile(session) -> ReaderProfile:
    reader = session.scalar(
        select(ReaderProfile)
        .where(ReaderProfile.active.is_(True))
        .order_by(ReaderProfile.created_at.asc(), ReaderProfile.id.asc())
    )
    if reader is None:
        raise HTTPException(status_code=404, detail="尚未建立新聞室讀者設定")
    return reader


def _clean_profile_values(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value.strip() for value in values if value.strip()))


def _reader_profile_payload(reader: ReaderProfile) -> dict[str, Any]:
    return jsonable_encoder({
        "id": reader.id,
        "preference_prompt": reader.preference_prompt or "",
        "included_topics": reader.included_topics or [],
        "excluded_topics": reader.excluded_topics or [],
        "included_subreddits": reader.included_subreddits or [],
        "excluded_subreddits": reader.excluded_subreddits or [],
        "included_keywords": reader.included_keywords or [],
        "excluded_keywords": reader.excluded_keywords or [],
        "timezone": reader.timezone,
        "delivery_time": reader.delivery_time,
    })


app = FastAPI(title="Reddit Tracker 控制台", docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory=STATIC_ROOT), name="static")


@app.get("/", include_in_schema=False)
def dashboard() -> FileResponse:
    return FileResponse(STATIC_ROOT / "dashboard.html")


@app.get("/daily/", include_in_schema=False)
@app.get("/daily/{edition_date}", include_in_schema=False)
def daily_edition_page(edition_date: date | None = None) -> FileResponse:
    """v2.0 綜合日報的網頁版；不帶日期時開最新一期。"""
    site = Path(get_settings().daily_site_dir)
    if edition_date is None:
        pages = sorted(site.glob("*.html"))
        if not pages:
            raise HTTPException(status_code=404, detail="尚未產生任何日報")
        return FileResponse(pages[-1])
    page = site / f"{edition_date.isoformat()}.html"
    if not page.is_file():
        raise HTTPException(status_code=404, detail="這一天沒有日報")
    return FileResponse(page)


@app.get("/api/overview")
def overview() -> dict[str, Any]:
    return _overview()


@app.get("/api/config")
def config() -> dict[str, Any]:
    return _settings_payload()


@app.put("/api/config")
def save_config(payload: SettingsUpdate) -> dict[str, Any]:
    try:
        update_env(payload.values)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _settings_payload()


@app.post("/api/services/start")
def start_services(action: ServiceAction) -> dict[str, Any]:
    try:
        results = []
        for index, label in enumerate(_labels(action)):
            if index:
                time.sleep(2)  # launchd 同 label 操作的短暫 rate limit
            results.append(_start_service(label))
    except (OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {"results": results, "services": service_statuses()}


@app.post("/api/services/stop")
def stop_services(action: ServiceAction) -> dict[str, Any]:
    try:
        results = [_stop_service(label) for label in _labels(action)]
    except (OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {"results": results, "services": service_statuses()}


@app.post("/api/llm/doctor")
def llm_doctor() -> dict[str, Any]:
    try:
        completed = _run([sys.executable, "scripts/llm_web_session_doctor.py"], timeout=25)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {"ready": completed.returncode == 0, "output": (completed.stdout + completed.stderr).strip()}


@app.get("/api/data/{kind}")
def data(kind: str, limit: int = Query(default=50, ge=1, le=200)) -> list[dict[str, Any]]:
    return _rows(kind, limit)


@app.get("/api/qa-sessions")
def qa_sessions(limit: int = Query(default=100, ge=1, le=200)) -> list[dict[str, Any]]:
    return _qa_sessions(limit)


@app.get("/api/qa-sessions/{session_id}/messages")
def qa_messages(session_id: int) -> list[dict[str, Any]]:
    with session_scope() as session:
        records = session.scalars(
            select(QAMessage)
            .where(QAMessage.qa_session_id == session_id)
            .order_by(QAMessage.sent_at.asc())
        ).all()
    return jsonable_encoder([
        {
            "id": message.id,
            "role": message.role,
            "content": message.content,
            "sent_at": message.sent_at,
            "input_tokens": message.input_tokens,
            "output_tokens": message.output_tokens,
            "cost_usd": message.cost_usd,
        }
        for message in records
    ])


@app.get("/api/newsroom/editions")
def newsroom_editions(limit: int = Query(default=30, ge=1, le=100)) -> list[dict[str, Any]]:
    return _newsroom_editions(limit)


@app.get("/api/newsroom/editions/{edition_id}")
def newsroom_edition(edition_id: int) -> dict[str, Any]:
    return _newsroom_edition(edition_id)


@app.get("/api/newsroom/pilot")
def newsroom_pilot() -> dict[str, Any]:
    return _newsroom_pilot()


@app.get("/api/newsroom/source-health")
def newsroom_source_health() -> dict[str, Any]:
    return _newsroom_source_health()


@app.get("/api/newsroom/reader-profile")
def newsroom_reader_profile() -> dict[str, Any]:
    with session_scope() as session:
        return _reader_profile_payload(_active_reader_profile(session))


@app.put("/api/newsroom/reader-profile")
def save_newsroom_reader_profile(payload: NewsroomReaderProfileUpdate) -> dict[str, Any]:
    with session_scope() as session:
        reader = _active_reader_profile(session)
        reader.preference_prompt = payload.preference_prompt.strip()
        reader.included_topics = _clean_profile_values(payload.included_topics)
        reader.excluded_topics = _clean_profile_values(payload.excluded_topics)
        reader.included_subreddits = _clean_profile_values(payload.included_subreddits)
        reader.excluded_subreddits = _clean_profile_values(payload.excluded_subreddits)
        reader.included_keywords = _clean_profile_values(payload.included_keywords)
        reader.excluded_keywords = _clean_profile_values(payload.excluded_keywords)
        session.flush()
        return _reader_profile_payload(reader)


@app.post("/api/newsroom/items/{item_id}/feedback")
def newsroom_feedback(item_id: int, payload: NewsroomFeedbackAction) -> dict[str, Any]:
    with session_scope() as session:
        item = session.get(EditionItem, item_id)
        if item is None:
            raise HTTPException(status_code=404, detail="找不到此報紙項目")
        edition = session.get(NewsroomEdition, item.edition_id)
        if edition is None:
            raise HTTPException(status_code=409, detail="報紙項目缺少版次")
        reader = edition.reader
        outcome = record_reader_feedback(session, reader=reader, edition_item=item, action=payload.action)
        if outcome.feedback is None:
            raise HTTPException(status_code=400, detail="無法記錄此回饋")
        return {
            "id": outcome.feedback.id,
            "action": outcome.feedback.action,
            "duplicate": outcome.duplicate,
        }


@app.get("/api/logs/{name}")
def logs(name: Literal["scheduler", "bot", "newsroom"]) -> dict[str, str]:
    return {"content": _tail(LOG_PATHS[name])}


def main() -> None:
    """以 `uv run python -m reddit_tracker.web` 啟動本機控制台。"""
    url = "http://127.0.0.1:8765"
    webbrowser.open(url)
    uvicorn.run(app, host="127.0.0.1", port=8765, log_level="warning")


if __name__ == "__main__":
    main()

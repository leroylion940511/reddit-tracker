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
from pathlib import Path
from typing import Any, Literal

import uvicorn
from fastapi import FastAPI, HTTPException, Query
from fastapi.encoders import jsonable_encoder
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy import func, inspect, select

from .config import Settings, get_settings
from .db import session_scope
from .models import (
    CandidatePost,
    DailyPush,
    Feedback,
    LLMRecord,
    QAMessage,
    QASession,
    RelatedPost,
    ScoringRecord,
    TrackedPost,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
STATIC_ROOT = Path(__file__).resolve().parent / "static"
ENV_PATH = PROJECT_ROOT / ".env"
LOG_PATHS = {
    "scheduler": PROJECT_ROOT / "scheduler.log",
    "bot": PROJECT_ROOT / "bot.log",
}
SERVICE_LABELS = (
    "com.leroy.reddit-tracker.scheduler",
    "com.leroy.reddit-tracker.bot",
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
    service: Literal["scheduler", "bot", "all"] = "all"


def _run(command: list[str], *, timeout: float = 12.0) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, text=True, capture_output=True, timeout=timeout, check=False)


def _label_for(service: str) -> str:
    label = f"com.leroy.reddit-tracker.{service}"
    if label not in SERVICE_LABELS:
        raise HTTPException(status_code=400, detail="未知的服務名稱")
    return label


def _labels(action: ServiceAction) -> tuple[str, ...]:
    if action.service == "all":
        return SERVICE_LABELS
    return (_label_for(action.service),)


def _service_status(label: str) -> dict[str, Any]:
    uid = str(os.getuid())
    target = f"gui/{uid}/{label}"
    printed = _run(["launchctl", "print", target])
    disabled = _run(["launchctl", "print-disabled", f"gui/{uid}"])
    disabled_flag = f'"{label}" => true' in disabled.stdout
    return {
        "label": label,
        "name": "排程器" if label.endswith("scheduler") else "Telegram Bot",
        "running": printed.returncode == 0,
        "disabled": disabled_flag,
        "plist_installed": PLIST_DESTINATIONS[label].exists(),
        "detail": (printed.stderr or printed.stdout).strip()[-300:],
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
        }
        latest = {
            "candidate": session.scalar(select(func.max(CandidatePost.discovered_at))),
            "qa": session.scalar(select(func.max(QAMessage.sent_at))),
            "llm": session.scalar(select(func.max(LLMRecord.called_at))),
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


app = FastAPI(title="Reddit Tracker 控制台", docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory=STATIC_ROOT), name="static")


@app.get("/", include_in_schema=False)
def dashboard() -> FileResponse:
    return FileResponse(STATIC_ROOT / "dashboard.html")


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


@app.get("/api/logs/{name}")
def logs(name: Literal["scheduler", "bot"]) -> dict[str, str]:
    return {"content": _tail(LOG_PATHS[name])}


def main() -> None:
    """以 `uv run python -m reddit_tracker.web` 啟動本機控制台。"""
    url = "http://127.0.0.1:8765"
    webbrowser.open(url)
    uvicorn.run(app, host="127.0.0.1", port=8765, log_level="warning")


if __name__ == "__main__":
    main()

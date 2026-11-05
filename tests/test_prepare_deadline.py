"""06:00 準備的 LLM 截止時間（llm/deadline.py）：2026-11-05 記者兩次卡滿 300 秒逾時。

不執行 codex：subprocess.run 一律換成假的。
"""

from __future__ import annotations

import json
import subprocess
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select

from reddit_tracker.daily import run as run_module
from reddit_tracker.daily.evidence import EvidenceItem
from reddit_tracker.daily.mas.orchestrator import run_mas
from reddit_tracker.daily.scoring import ScoredCluster, Selection
from reddit_tracker.llm import codex as codex_module
from reddit_tracker.llm.codex import CodexClient
from reddit_tracker.llm.deadline import (
    MIN_ATTEMPT_SECONDS,
    DeadlinePassed,
    attempt_timeout,
    current_deadline,
    deadline_on,
    llm_deadline,
)
from reddit_tracker.llm.quota import ModelQuotaGuard
from reddit_tracker.models import PagePlan, StoryVersion
from reddit_tracker.newsroom import scheduler
from tests.test_mas_steps import DAY, NOW, SECTIONS, _item, _registry, _snapshot


def _utc(**delta) -> datetime:
    return datetime.now(timezone.utc) + timedelta(**delta)


def test_attempt_timeout_caps_at_deadline_and_refuses_near_it():
    assert attempt_timeout(150) == 150  # 沒綁截止＝照舊
    now = datetime(2026, 11, 6, 0, 0, tzinfo=timezone.utc)
    with llm_deadline(now + timedelta(seconds=60)):
        assert attempt_timeout(150, now=now) == 60
        assert attempt_timeout(30, now=now) == 30
        with pytest.raises(DeadlinePassed):
            attempt_timeout(150, now=now + timedelta(seconds=60 - MIN_ATTEMPT_SECONDS + 1))
        # 巢狀取較早的；內層結束後恢復外層
        with llm_deadline(now + timedelta(hours=1)) as inner:
            assert inner == now + timedelta(seconds=60)
        with llm_deadline(now + timedelta(seconds=30)) as inner:
            assert inner == now + timedelta(seconds=30)
        assert current_deadline() == now + timedelta(seconds=60)
    assert current_deadline() is None


def test_deadline_on_is_local_time():
    at = deadline_on(date(2026, 11, 6), "08:20", "Asia/Taipei")
    assert at.astimezone(timezone.utc) == datetime(2026, 11, 6, 0, 20, tzinfo=timezone.utc)


@pytest.fixture()
def codex(monkeypatch, tmp_path):
    settings = SimpleNamespace(
        codex_bin="/usr/local/bin/codex", codex_model="m", codex_reasoning_effort="low", codex_timeout_seconds=150,
        codex_max_retries=1, llm_daily_limit=60, llm_quota_state_path=str(tmp_path / "quota.json"),
        telegram_bot_token=None, gemini_api_key=None, rsshub_access_key=None,
    )
    monkeypatch.setattr(codex_module, "get_settings", lambda: settings)
    calls = []

    def run(cmd, *, input, cwd, timeout, **kwargs):
        calls.append(timeout)
        Path(cmd[cmd.index("-o") + 1]).write_text('{"ok":true}', encoding="utf-8")
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(codex_module.subprocess, "run", run)
    client = CodexClient(guard=ModelQuotaGuard(state_path=settings.llm_quota_state_path, daily_limit=60))
    return SimpleNamespace(client=client, calls=calls)


KWARGS = dict(system="s", messages=[{"role": "user", "content": "u"}], max_output_tokens=1, temperature=0)


def test_codex_attempt_timeout_never_runs_past_deadline(codex):
    codex.client.complete(**KWARGS)
    assert codex.calls == [150]
    with llm_deadline(_utc(seconds=90)):
        codex.client.complete(**KWARGS)
    assert 80 < codex.calls[-1] <= 90


def test_codex_after_deadline_spends_no_quota_and_runs_nothing(codex):
    with llm_deadline(_utc(seconds=5)), pytest.raises(DeadlinePassed):
        codex.client.complete(**KWARGS)
    assert codex.calls == []
    assert codex.client.guard.used("m") == 0


def _evidence(n: int) -> list[EvidenceItem]:
    return [EvidenceItem(
        outlet=f"o{n}", source_id=f"s{n}", source_name="中央社", tier="T2", lang="zh-Hant",
        title=f"標題{n}", summary=f"摘要{n}。", url=f"https://www.cna.com.tw/{n}", published_at="2026-11-06T05:00+08:00",
    )]


def test_pipeline_writer_stops_retrying_after_deadline(monkeypatch):
    class Late:
        name = "codex"
        requests = 0

        def write(self, label, stories):
            self.requests += 1
            raise DeadlinePassed("過了截止")

    monkeypatch.setattr(run_module.time, "sleep", lambda s: pytest.fail("過了截止不該再等 15 秒重試"))
    writer = Late()
    planned = [run_module.Planned(1, Selection(ScoredCluster(1, "world", "report", 1.0), "world", 1, False), _evidence(1))]
    written = run_module._write_all(planned, {"world": "國際"}, writer)
    assert writer.requests == 1
    assert written[1].writer == "template"
    assert any("DeadlinePassed" in note for note in written[1].review_notes)


def test_mas_after_deadline_degrades_to_template_instead_of_waiting(session):
    """每個角色呼叫都撞截止：整期照樣排出版面（模板稿），不卡住。"""
    raw = []
    for i, section in enumerate(SECTIONS):
        for j in range(2):
            item = _item(session, f"武契奇事件{i}-{j}", "國會選舉結果。", url=f"https://www.cna.com.tw/{i}/{j}")
            raw.append(_snapshot([item.id], i * 10 + j, section=section, score=100 - j))

    class Late:
        model = "m"
        calls = 0  # 這個 client 不該被呼叫

        def complete(self, **kwargs):
            self.calls += 1
            raise DeadlinePassed("過了截止")

    client = Late()
    with llm_deadline(_utc(seconds=5)):
        result = run_mas(session, edition_date=DAY, snapshot=SimpleNamespace(candidates=raw), registry=_registry(),
                         client=client, now=NOW)
    assert result.degraded == ["copy_editor", "fact_checker", "reporter"]
    assert client.calls == 0  # 額度當成 0：連呼叫都不開
    assert session.scalar(select(PagePlan)) is not None
    versions = session.scalars(select(StoryVersion)).all()
    assert len(versions) == len(raw) and all(v.body for v in versions)


def test_scheduler_binds_prepare_deadline(monkeypatch):
    seen = []
    settings = SimpleNamespace(newsroom_delivery_timezone="Asia/Taipei", daily_prepare_deadline="08:20", daily_mode="pipeline")
    monkeypatch.setattr(scheduler, "get_settings", lambda: settings)
    monkeypatch.setattr(scheduler, "check_codex_version", lambda s: None)
    monkeypatch.setattr(scheduler, "prepare_daily", lambda day: seen.append((day, current_deadline())) or 1)
    scheduler._prepare_daily_today()
    [(day, deadline)] = seen
    assert deadline == datetime.combine(day, datetime.min.time().replace(hour=8, minute=20), ZoneInfo("Asia/Taipei"))
    assert current_deadline() is None


def test_shadow_gets_its_own_cap_and_mas_keeps_the_outer_deadline(monkeypatch):
    seen = []
    settings = SimpleNamespace(daily_shadow_max_minutes=30, daily_annotation_dir="unused")
    monkeypatch.setattr(run_module, "get_settings", lambda: settings)

    class NoEdition:
        def __enter__(self):
            return SimpleNamespace(scalar=lambda *a, **k: None)

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr(run_module, "session_scope", NoEdition)
    monkeypatch.setattr(run_module, "prepare_daily", lambda day, **kw: seen.append((kw.get("shadow", False), current_deadline())) or 7)
    outer = _utc(hours=2)
    with llm_deadline(outer):
        assert run_module.prepare_with_shadow(date(2026, 11, 6)) == 7
    (shadow, shadow_deadline), (mas, mas_deadline) = seen
    assert shadow and not mas
    assert _utc(minutes=29) < shadow_deadline <= _utc(minutes=30)
    assert mas_deadline == outer


def test_default_settings_lower_codex_timeout_and_set_deadline():
    from reddit_tracker.config import Settings

    settings = Settings(_env_file=None)
    assert settings.codex_timeout_seconds == 150
    assert settings.daily_prepare_deadline == "08:20"
    with pytest.raises(ValueError):
        Settings(_env_file=None, daily_prepare_deadline="8點20")
    json.dumps(settings.daily_prepare_deadline)

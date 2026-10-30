"""P 組影子版自動排程（方案 B；手冊步驟 10、12、8.3）：P 先跑、M 後跑、同一份快照、額度分帳。

不呼叫真 LLM：撰稿用 test_daily 的 FakeWriter，M 組沒有 client 時走 _SilentClient（模板稿）。
"""

from __future__ import annotations

import json
import logging
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from reddit_tracker.daily import run as run_module
from reddit_tracker.daily.store import approve_story
from reddit_tracker.llm.quota import SHADOW_PURPOSE, ModelQuotaGuard, QuotaExhausted
from reddit_tracker.models import DailyArticle, DailyEdition, DailySnapshot, Story
from reddit_tracker.newsroom import scheduler
from tests.test_daily import EDITION, NOW, daily_env  # noqa: F401


@pytest.fixture()
def shadow_env(daily_env, tmp_path, monkeypatch):  # noqa: F811
    settings = run_module.get_settings()
    settings.daily_annotation_dir = str(tmp_path / "annotation")
    return daily_env


def _stories(session, variant):
    return session.scalars(select(Story).where(Story.edition_date == EDITION, Story.run_variant == variant)).all()


# ── 額度 ──────────────────────────────────────────────────────────────────


def test_shadow_purpose_cap_leaves_the_rest_of_the_daily_limit_for_mas(tmp_path):
    state = tmp_path / "q.json"
    guard = ModelQuotaGuard(state_path=state, daily_limit=5, purpose_limits={SHADOW_PURPOSE: 2})
    guard.acquire(model="m", purpose=SHADOW_PURPOSE)
    guard.acquire(model="m", purpose=SHADOW_PURPOSE)
    with pytest.raises(QuotaExhausted, match="shadow"):
        guard.acquire(model="m", purpose=SHADOW_PURPOSE)
    for _ in range(3):  # M 組（其他用途）還有 5 − 2 格
        guard.acquire(model="m", purpose="reporter")
    with pytest.raises(QuotaExhausted):
        guard.acquire(model="m", purpose="reporter")
    assert guard.used("m") == 5 and guard.used_by("m", SHADOW_PURPOSE) == 2
    # 另一個 process 沒設用途上限也照總數算
    assert ModelQuotaGuard(state_path=state, daily_limit=5).used("m") == 5


def test_codex_client_guard_gets_the_shadow_cap(monkeypatch, tmp_path):
    from reddit_tracker.llm import codex as codex_module

    settings = SimpleNamespace(
        codex_bin="/bin/false", codex_model="m", codex_reasoning_effort="low", codex_timeout_seconds=1,
        codex_max_retries=1, llm_quota_state_path=str(tmp_path / "q.json"), llm_daily_limit=60,
        daily_shadow_llm_limit=7, telegram_bot_token=None, gemini_api_key=None, rsshub_access_key=None,
        daily_model_version=None,
    )
    monkeypatch.setattr(codex_module, "get_settings", lambda: settings)
    client = codex_module.CodexClient(purpose=SHADOW_PURPOSE)
    assert client.guard.purpose_limits == {SHADOW_PURPOSE: 7}


def test_shadow_writer_uses_the_shadow_purpose(shadow_env, monkeypatch):
    seen = []

    def make(name, **kw):
        seen.append(kw.get("purpose", "daily"))
        return shadow_env.writer

    monkeypatch.setattr(run_module, "DailyWriter", make)
    run_module.prepare_daily(EDITION, now=NOW, shadow=True)
    run_module.prepare_daily(EDITION, now=NOW, mode="mas")
    assert seen == [SHADOW_PURPOSE, "daily"]


def test_settings_defaults_keep_shadow_off():
    from reddit_tracker.config import Settings

    settings = Settings(_env_file=None)
    assert settings.daily_shadow_enabled is False
    assert settings.daily_shadow_llm_limit == 12
    assert settings.daily_annotation_dir == "annotation"


# ── 排程 ──────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("mode", "flag", "expected"),
    [("mas", False, "prepare"), ("pipeline", True, "prepare"), ("pipeline", False, "prepare"), ("mas", True, "shadow")],
)
def test_prepare_job_runs_shadow_only_for_mas_with_flag(monkeypatch, mode, flag, expected):
    calls = []
    settings = SimpleNamespace(newsroom_delivery_timezone="Asia/Taipei", daily_mode=mode, daily_shadow_enabled=flag)
    monkeypatch.setattr(scheduler, "get_settings", lambda: settings)
    monkeypatch.setattr(scheduler, "prepare_daily", lambda day: calls.append("prepare") or 1)
    monkeypatch.setattr(scheduler, "prepare_with_shadow", lambda day: calls.append("shadow") or 1)
    scheduler._prepare_daily_today()
    assert calls == [expected]


# ── P 先、M 後 ────────────────────────────────────────────────────────────


def test_shadow_then_mas_share_one_snapshot_and_only_mas_is_the_edition(shadow_env):
    edition_id = run_module.prepare_with_shadow(EDITION, now=NOW)
    session = shadow_env.session

    editions = session.scalars(select(DailyEdition)).all()
    assert [e.id for e in editions] == [edition_id]
    edition = editions[0]
    assert edition.status == "drafted" and edition.stats["run_variant"] == "mas"

    p_stories, m_stories = _stories(session, "pipeline"), _stories(session, "mas")
    assert p_stories and m_stories
    p_ids = {s.id for s in p_stories}
    # 發行版面只有 M 稿：daily_articles 的 cluster 都來自 M 稿，HTML 不含 P 稿
    m_keepers = {s.keeper_cluster_id for s in m_stories}
    assert {a.cluster_id for a in edition.articles} <= m_keepers
    assert session.scalar(select(DailyArticle).where(DailyArticle.edition_id != edition_id)) is None
    snapshots = session.scalars(select(DailySnapshot)).all()
    assert len(snapshots) == 1
    assert {r["keeper_cluster_id"] for r in snapshots[0].candidates} >= {s.keeper_cluster_id for s in p_stories}
    # 跨語言合併（編輯會議）只跑一次：P 影子 1 次 desk＋版數；M 從快照開始不再開會
    assert shadow_env.writer.requests == 3  # 編輯會議＋頭版＋台灣版，全部算在 P 影子
    assert (shadow_env.tmp_path / "shadow" / "2026-10-28.html").is_file()

    # 例行核准 M 稿不受影響；P 稿不需要核准
    m_story = m_stories[0]
    row = approve_story(session, m_story.id, by="Leroy", now=NOW)
    assert row.status == "approved" and m_story.id not in p_ids


def test_publish_after_shadow_sends_only_mas(shadow_env, monkeypatch):
    run_module.get_settings().daily_mode = "mas"
    run_module.prepare_with_shadow(EDITION, now=NOW)
    sent = []

    async def fake_send(token, chat_id, text, html_path, filename):
        sent.append((text, html_path.read_text(encoding="utf-8")))
        return [1, 2]

    monkeypatch.setattr(run_module, "_send", fake_send)
    edition_id = run_module.publish_daily(EDITION)
    assert shadow_env.session.get(DailyEdition, edition_id).status == "published"
    assert len(sent) == 1
    text, html = sent[0]
    assert "稿件1號標題" not in text and "稿件1號標題" not in html  # FakeWriter 寫的 P 稿不會出現在發行版
    assert (shadow_env.tmp_path / "shadow" / "2026-10-28.html").read_text(encoding="utf-8").count("稿件") > 0


def test_mas_from_shadow_snapshot_skips_second_editorial_meeting(shadow_env):
    run_module.prepare_daily(EDITION, now=NOW, shadow=True)
    after_shadow = shadow_env.writer.requests
    row = shadow_env.session.scalar(select(DailySnapshot))
    run_module.prepare_daily(EDITION, now=NOW, mode="mas", snapshot={"candidates": list(row.candidates)})
    assert shadow_env.writer.requests == after_shadow  # M 沒有再呼叫 find_same_events


def test_shadow_failure_only_logs_and_mas_still_drafts(shadow_env, monkeypatch, caplog):
    real = run_module.prepare_daily

    def flaky(edition_date, **kw):
        if kw.get("shadow"):
            raise RuntimeError("shadow boom")
        return real(edition_date, **kw)

    monkeypatch.setattr(run_module, "prepare_daily", flaky)
    with caplog.at_level(logging.ERROR, logger=run_module.__name__):
        edition_id = run_module.prepare_with_shadow(EDITION, now=NOW)
    edition = shadow_env.session.get(DailyEdition, edition_id)
    assert edition.status == "drafted" and edition.stats["run_variant"] == "mas"
    assert not _stories(shadow_env.session, "pipeline")
    assert "pipeline shadow 2026-10-28 failed" in caplog.text
    assert not (shadow_env.tmp_path / "annotation" / "2026-10-28").exists()  # 只有 P、M 都有稿才匯出


def test_shadow_skipped_when_edition_already_exists(shadow_env):
    first = run_module.prepare_daily(EDITION, now=NOW, mode="mas")
    snapshot_before = shadow_env.session.scalar(select(DailySnapshot)).candidates
    assert run_module.prepare_with_shadow(EDITION, now=NOW) == first
    assert not _stories(shadow_env.session, "pipeline")
    assert shadow_env.session.scalar(select(DailySnapshot)).candidates == snapshot_before


def test_annotation_export_writes_blind_spot_and_private_mapping(shadow_env):
    run_module.prepare_with_shadow(EDITION, now=NOW)
    out = shadow_env.tmp_path / "annotation" / "2026-10-28"
    blind = (out / "blind.txt").read_text(encoding="utf-8")
    assert "#1" in blind and "pipeline" not in blind and "mas" not in blind
    assert (out / "spot-check.txt").read_text(encoding="utf-8").startswith("# 抽查 2026-10-28")
    assert not (out / "_private").exists()
    private = shadow_env.tmp_path / "annotation" / "_private" / "2026-10-28" / "mapping.json"
    mapping = json.loads(private.read_text(encoding="utf-8"))
    assert {m["variant"] for m in mapping.values()} == {"pipeline", "mas"}
    from reddit_tracker.daily.blind import mapping_digest

    assert (out / "mapping.sha256").read_text().strip() == mapping_digest(mapping)


def test_annotation_export_failure_does_not_fail_prepare(shadow_env, monkeypatch, caplog):
    monkeypatch.setattr(run_module, "export_annotation", lambda *a, **k: (_ for _ in ()).throw(OSError("disk")))
    with caplog.at_level(logging.ERROR, logger=run_module.__name__):
        edition_id = run_module.prepare_with_shadow(EDITION, now=NOW)
    assert shadow_env.session.get(DailyEdition, edition_id).status == "drafted"
    assert "annotation export 2026-10-28 failed" in caplog.text

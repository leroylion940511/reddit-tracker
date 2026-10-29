"""v2.0 comprehensive daily: scoring, selection, merging, review gate, prepare/publish."""

from __future__ import annotations

import hashlib
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from reddit_tracker.collection.clustering import cluster_recent_items
from reddit_tracker.daily import run as run_module
from reddit_tracker.daily.evidence import EvidenceItem
from reddit_tracker.daily.scoring import (
    ScoredCluster,
    apply_merges,
    kind_for,
    select_articles,
)
from reddit_tracker.daily.writer import (
    SINGLE_SOURCE_NOTICE,
    WrittenStory,
    finalize_story,
    review_story,
    template_story,
)
from reddit_tracker.models import DailyArticle, DailyEdition, SourceItem, StoryCluster
from reddit_tracker.seeds.news_sources import SourceRegistry

NOW = datetime(2026, 10, 27, 22, 0, tzinfo=timezone.utc)  # 10/28 06:00 台北
EDITION = date(2026, 10, 28)


def _ev(name="中央社 政治", lang="zh-Hant", title="標題", summary="摘要", published="2026-10-27T10:00+08:00"):
    return EvidenceItem(
        outlet=name, source_id=name, source_name=name, tier="T2", lang=lang, title=title,
        summary=summary, url="https://example.com/a", published_at=published,
    )


# ── scoring / selection ──────────────────────────────────────────────────


def test_kind_follows_evidence_rules():
    assert kind_for(StoryCluster(outlet_count=2, t1_count=0)) == "report"
    assert kind_for(StoryCluster(outlet_count=1, t1_count=1)) == "report"
    assert kind_for(StoryCluster(outlet_count=1, t1_count=0)) == "single_source"
    assert kind_for(StoryCluster(outlet_count=0, t1_count=0)) == "social"


def test_select_caps_front_page_per_section_and_respects_kinds():
    scored = [ScoredCluster(i, "world", "report", 100 - i) for i in range(1, 6)]
    scored += [ScoredCluster(10, "taiwan", "report", 50), ScoredCluster(11, "taiwan", "single_source", 49)]
    scored += [ScoredCluster(20, "social", "social", 2), ScoredCluster(21, "social", "report", 60)]
    selections = select_articles(scored)
    front = [s.cluster.cluster_id for s in selections if s.is_front]
    assert front == [1, 2, 21, 10]  # 國際最多 2 則；social 版的 report 可上頭版
    social = [s.cluster.cluster_id for s in selections if s.section == "social" and not s.is_front]
    assert social == [20]
    taiwan = [s.cluster.cluster_id for s in selections if s.section == "taiwan" and not s.is_front]
    assert taiwan == [11]
    assert len({s.cluster.cluster_id for s in selections}) == len(selections)


def test_apply_merges_keeps_highest_score_and_upgrades_kind():
    scored = [
        ScoredCluster(1, "world", "single_source", 30),
        ScoredCluster(2, "world", "report", 20),
        ScoredCluster(3, "world", "report", 10),
    ]
    merged = apply_merges(scored, [[1, 2], [2, 99]])
    assert [s.cluster_id for s in merged] == [1, 3]
    assert merged[0].kind == "report"
    assert merged[0].all_ids == [1, 2]
    assert merged[0].signals["merged_cluster_ids"] == [2]


# ── writer / review ──────────────────────────────────────────────────────


def test_review_flags_unsupported_numbers_but_allows_unit_conversions():
    evidence = [_ev(title="Meta plans $95 billion offering", lang="en", summary="raises 40 billion; 3 arrested")]
    ok = WrittenStory("Meta 擬募資 950 億美元", "", "據報導，Meta 計畫募資 950 億美元，另有 400 億，3 人被捕。" * 2, "", "gemini")
    assert review_story(ok, evidence) == []
    bad = WrittenStory("Meta 擬募資 1200 億美元", "", "據報導，Meta 計畫募資 1200 億美元。" * 4, "", "gemini")
    assert any("1200" in problem for problem in review_story(bad, evidence))
    short = WrittenStory("短", "", "太短", "", "gemini")
    assert len(review_story(short, evidence)) == 2


def test_template_prefers_chinese_lead_and_labels_kind():
    evidence = [_ev("BBC World", lang="en", title="English title"), _ev("中央社 國際", title="中文標題", summary="中文摘要")]
    story = template_story(evidence, "single_source")
    assert story.headline == "中文標題"
    assert story.body.startswith("據中央社報導：中文摘要")
    assert "BBC World" in story.body and "單一媒體" not in story.body  # 警語由 finalize_story 加
    story = finalize_story(story, evidence, "single_source")
    assert story.body.split("\n")[-1] == SINGLE_SOURCE_NOTICE
    assert story.writer == "template"


# ── prepare / publish ────────────────────────────────────────────────────


REGISTRY = SourceRegistry(
    version=1,
    sections={"taiwan": "台灣", "world": "國際", "social": "社群觀察", "data": "數據欄"},
    sources=[
        {"id": "cna-world", "name": "中央社 國際", "section": "world", "tier": "T2", "method": "rss",
         "url": "https://cna.com.tw/rss", "lang": "zh-Hant"},
        {"id": "ltn-world", "name": "自由時報 國際", "section": "world", "tier": "T2", "method": "rss",
         "url": "https://ltn.com.tw/rss", "lang": "zh-Hant"},
        {"id": "rti-news", "name": "中央廣播電台", "section": "taiwan", "tier": "T2", "method": "rss",
         "url": "https://rti.org.tw/rss", "lang": "zh-Hant", "general_feed": True},
        {"id": "ptt", "name": "PTT 八卦板", "section": "social", "tier": "T4", "method": "rss",
         "url": "https://ptt.cc/atom", "lang": "zh-Hant"},
    ],
)


def _add(session, source_id, host, title, summary, *, section, tier="T2", hours_ago=3):
    url = f"https://{host}/{hashlib.sha1(title.encode()).hexdigest()[:8]}"
    session.add(SourceItem(
        source_id=source_id, section=section, tier=tier,
        item_key=hashlib.sha1(f"{source_id}{url}".encode()).hexdigest(), url=url, canonical_url=url,
        title=title, summary=summary, lang="zh-Hant", published_at=NOW - timedelta(hours=hours_ago),
        first_seen_at=NOW - timedelta(hours=hours_ago),
    ))


class FakeWriter:
    name = "codex"

    def __init__(self, fail_times=0):
        self.requests = 0
        self.fail_times = fail_times

    def find_same_events(self, candidates):
        self.requests += 1
        return []

    def write(self, label, stories):
        self.requests += 1
        if self.fail_times:
            self.fail_times -= 1
            raise ValueError("broken JSON")
        return {
            key: WrittenStory(f"{label}稿件{key}號標題", "一句話重點", "據中央社報導，這是一則測試正文。" * 6, "影響", "codex")
            for key, _, _ in stories
        }


@pytest.fixture()
def daily_env(session, monkeypatch, tmp_path):
    _add(session, "cna-world", "cna.com.tw", "塞爾維亞總統武契奇承認敗選", "塞爾維亞國會大選學生運動勝出，武契奇承認敗選", section="world")
    _add(session, "ltn-world", "news.ltn.com.tw", "武契奇承認敗選 塞爾維亞學運勝出", "塞爾維亞國會大選，武契奇承認敗選，學生運動勝出", section="world")
    _add(session, "rti-news", "rti.org.tw", "塞爾維亞大選 武契奇承認敗選學運勝", "塞爾維亞國會大選武契奇承認敗選", section="taiwan")
    _add(session, "ptt", "ptt.cc", "[問卦] 有沒有颱風假的八卦", "颱風假要不要放", section="social", tier="T4")
    session.flush()
    cluster_recent_items(session, now=NOW, general_sources=REGISTRY.general_source_ids())
    session.commit()

    @contextmanager
    def scope():
        yield session
        session.commit()

    writer = FakeWriter()
    settings = SimpleNamespace(
        daily_writer="codex", codex_bin="/bin/sh", gemini_api_key="x", news_sources_path="unused", daily_site_dir=str(tmp_path),
        newsroom_delivery_timezone="Asia/Taipei", telegram_bot_token="t", telegram_chat_id="42",
    )
    monkeypatch.setattr(run_module, "session_scope", scope)
    monkeypatch.setattr(run_module, "get_settings", lambda: settings)
    monkeypatch.setattr(run_module, "load_registry", lambda path: REGISTRY)
    monkeypatch.setattr(run_module, "fetch_market_box", lambda: None)
    monkeypatch.setattr(run_module, "DailyWriter", lambda name: writer)
    monkeypatch.setattr(run_module, "RETRY_DELAY_SECONDS", 0)
    return SimpleNamespace(session=session, writer=writer, tmp_path=tmp_path)


def test_prepare_builds_edition_with_front_page_social_and_html(daily_env):
    edition_id = run_module.prepare_daily(EDITION, now=NOW)

    edition = daily_env.session.get(DailyEdition, edition_id)
    assert edition.status == "drafted" and edition.writer == "codex"
    articles = {a.section: a for a in edition.articles}
    serbia = articles["world"]
    assert serbia.is_front and serbia.kind == "report"
    assert len(serbia.sources) == 3  # 中央社、自由、央廣三家出處
    assert articles["social"].kind == "social" and not articles["social"].is_front
    html = (daily_env.tmp_path / "2026-10-28.html").read_text(encoding="utf-8")
    assert "頭版" in html and "社群觀察" in html and "本版今日無新稿" in html
    assert edition.stats["llm_requests"] == 3  # 編輯會議＋頭版＋社群版

    # 已有 draft 時再次 prepare 不重寫、不再呼叫 LLM
    assert run_module.prepare_daily(EDITION, now=NOW) == edition_id
    assert daily_env.writer.requests == 3


def test_writer_failures_retry_then_fall_back_to_template(daily_env):
    daily_env.writer.fail_times = 2  # 頭版兩次（WRITE_ATTEMPTS）都失敗
    edition_id = run_module.prepare_daily(EDITION, now=NOW)
    edition = daily_env.session.get(DailyEdition, edition_id)
    front = next(a for a in edition.articles if a.is_front)
    assert front.writer == "template"
    assert "2 次" in front.review_notes[0]
    assert edition.writer == "mixed"


def test_earlier_editions_exclude_clusters_but_refresh_does_not(daily_env):
    run_module.prepare_daily(EDITION, now=NOW)
    refreshed = run_module.prepare_daily(EDITION, now=NOW, refresh=True)
    assert len(daily_env.session.get(DailyEdition, refreshed).articles) == 2
    with pytest.raises(run_module.DailyEditionError):
        run_module.prepare_daily(EDITION + timedelta(days=1), now=NOW)  # 全部事件昨天已刊登


def test_publish_sends_once_and_marks_failures(daily_env, monkeypatch):
    sent = []

    async def fake_send(token, chat_id, text, html_path, filename):
        sent.append((chat_id, filename, html_path.exists()))
        return [1, 2]

    monkeypatch.setattr(run_module, "_send", fake_send)
    edition_id = run_module.publish_daily(EDITION, now=NOW)
    run_module.publish_daily(EDITION, now=NOW)
    edition = daily_env.session.get(DailyEdition, edition_id)
    assert edition.status == "published" and edition.telegram_message_ids == [1, 2]
    assert sent == [(42, "AI綜合日報-2026-10-28.html", True)]

    async def broken_send(*args):
        raise RuntimeError("network")

    edition.status = "drafted"
    daily_env.session.commit()
    monkeypatch.setattr(run_module, "_send", broken_send)
    with pytest.raises(RuntimeError):
        run_module.publish_daily(EDITION, now=NOW)
    assert edition.status == "delivery_failed"
    with pytest.raises(run_module.DailyEditionError):
        run_module.publish_daily(EDITION, now=NOW)
    assert daily_env.session.scalar(select(DailyArticle).limit(1)) is not None


@pytest.mark.parametrize("enabled", [False, True])
def test_daily_jobs_registered_only_when_enabled(monkeypatch, enabled):
    from reddit_tracker.newsroom import scheduler

    settings = SimpleNamespace(
        newsroom_delivery_timezone="Asia/Taipei",
        news_collection_enabled=False, daily_edition_enabled=enabled,
        daily_prepare_hour=6, daily_prepare_minute=0, daily_delivery_hour=8, daily_delivery_minute=35,
    )
    monkeypatch.setattr(scheduler, "get_settings", lambda: settings)
    jobs = {job.id: job for job in scheduler.build_scheduler().get_jobs()}
    assert ({"daily_prepare_edition", "daily_publish_edition"} <= set(jobs)) is enabled
    if enabled:
        assert "hour='8'" in str(jobs["daily_publish_edition"].trigger)
        assert "minute='35'" in str(jobs["daily_publish_edition"].trigger)


def test_writer_accepts_bare_list_responses():
    from reddit_tracker.daily.writer import DailyWriter
    from reddit_tracker.llm.gemini import GeminiResult

    class Client:
        def __init__(self, content):
            self.content = content

        def complete(self, **kwargs):
            return GeminiResult(content=self.content, input_tokens=0, output_tokens=0, cached_tokens=0)

    writer = DailyWriter(client=Client('[{"id":7,"headline":"標題標題","body":"正文","deck":"","why_it_matters":""}]'))
    assert writer.write("台灣", [(7, "report", [_ev()])])[7].headline == "標題標題"
    writer = DailyWriter(client=Client('[[1,2],[3]]'))
    assert writer.find_same_events([(1, "a"), (2, "b"), (3, "c")]) == [[1, 2]]


def test_prepare_falls_back_to_template_when_codex_missing(daily_env, monkeypatch):
    settings = run_module.get_settings()
    settings.codex_bin = "/nonexistent/codex"
    edition = daily_env.session.get(DailyEdition, run_module.prepare_daily(EDITION, now=NOW))
    assert edition.writer == "template" and daily_env.writer.requests == 0


# ── 手冊步驟 1：停用來源、MVP 版面、額度降級、fake provider ─────────────────


REGISTRY_SOCIAL_OFF = REGISTRY.model_copy(update={
    "sources": [
        s.model_copy(update={"enabled": False, "notes": "2026-10-28 停用：社群來源，不在 MVP"})
        if s.section == "social" else s
        for s in REGISTRY.sources
    ]
})


def test_disabled_source_material_already_in_db_is_not_selected(daily_env, monkeypatch):
    # daily_env 已把 PTT 素材聚合成一個社群事件；停用來源後重編不得再選它。
    monkeypatch.setattr(run_module, "load_registry", lambda path: REGISTRY_SOCIAL_OFF)
    edition = daily_env.session.get(DailyEdition, run_module.prepare_daily(EDITION, now=NOW))
    assert [a.section for a in edition.articles] == ["world"]
    assert all(src["source_id"] != "ptt" for a in edition.articles for src in a.sources)
    assert edition.stats["candidate_clusters"] == 1
    html = (daily_env.tmp_path / "2026-10-28.html").read_text(encoding="utf-8")
    assert "本版未開放" in html and "颱風假" not in html


def test_score_and_evidence_drop_disabled_members_of_mixed_clusters(session):
    from reddit_tracker.daily.evidence import build_evidence
    from reddit_tracker.daily.scoring import score_candidates

    _add(session, "cna-world", "cna.com.tw", "塞爾維亞總統武契奇承認敗選", "塞爾維亞國會大選學生運動勝出，武契奇承認敗選", section="world")
    _add(session, "ptt", "ptt.cc", "[新聞] 塞爾維亞總統武契奇承認敗選", "塞爾維亞國會大選學生運動勝出，武契奇承認敗選", section="social", tier="T4")
    _add(session, "ptt", "ptt.cc", "[問卦] 有沒有颱風假的八卦", "颱風假要不要放", section="social", tier="T4")
    session.flush()
    cluster_recent_items(session, now=NOW)
    mixed = session.scalar(select(SourceItem).where(SourceItem.source_id == "cna-world")).cluster_id
    assert len(session.scalars(select(SourceItem).where(SourceItem.cluster_id == mixed)).all()) == 2

    disabled = frozenset({"ptt"})
    everything = score_candidates(session, edition_date=EDITION, now=NOW)
    scored = score_candidates(session, edition_date=EDITION, now=NOW, disabled_sources=disabled)
    assert len(everything) == 2
    assert [s.cluster_id for s in scored] == [mixed]  # 只有 PTT 的事件消失
    evidence = build_evidence(session, [mixed], {}, disabled)
    assert [e.source_id for e in evidence.items] == ["cna-world"]


def test_render_marks_non_mvp_sections_as_not_open():
    from reddit_tracker.daily.render import MVP_SECTIONS, render_html

    assert MVP_SECTIONS == ("taiwan", "world", "tech")
    edition = DailyEdition(edition_date=EDITION, stats={})
    html = render_html(edition, {"taiwan": "台灣", "sports": "體育", "social": "社群觀察", "data": "數據欄"})
    taiwan, rest = html.split('id="taiwan"')[1].split('id="sports"')
    assert "本版今日無新稿" in taiwan and "本版未開放" not in taiwan
    assert rest.count("本版未開放") == 2  # 體育、社群觀察


def test_quota_exhaustion_falls_back_to_template_without_retrying(daily_env):
    from reddit_tracker.llm.quota import QuotaExhausted

    calls = []

    def exhausted(label, stories):
        calls.append(label)
        raise QuotaExhausted("m 本機每日額度 60 已用完")

    daily_env.writer.write = exhausted
    edition = daily_env.session.get(DailyEdition, run_module.prepare_daily(EDITION, now=NOW))
    assert {a.writer for a in edition.articles} == {"template"}
    assert len(calls) == 2  # 頭版、社群版各試一次就放棄，不等重試


def test_fake_provider_writes_offline_without_quota():
    from reddit_tracker.daily.writer import DailyWriter

    writer = DailyWriter("fake")
    assert writer.find_same_events([(1, "a"), (2, "b")]) == []
    stories = writer.write("國際", [(5, "report", [_ev(title="塞爾維亞大選", summary="武契奇承認敗選")])])
    assert stories[5].headline == "塞爾維亞大選" and stories[5].writer == "fake"
    assert "武契奇承認敗選" in stories[5].body
    assert writer.client.calls == 2


def test_default_daily_writer_does_not_build_gemini(monkeypatch):
    from reddit_tracker.daily import writer as writer_module
    from reddit_tracker.llm import gemini

    def boom(*args, **kwargs):
        raise AssertionError("日報不應建立 GeminiClient")

    monkeypatch.setattr(gemini, "GeminiClient", boom)
    assert type(writer_module.DailyWriter("codex").client).__name__ == "CodexClient"

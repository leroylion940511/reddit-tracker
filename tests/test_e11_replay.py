"""E11 重播：沒有真錄音就 skip；有錄音才離線重跑記者與文稿編輯。不呼叫 Codex。"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from reddit_tracker.daily.evidence import EvidenceItem
from reddit_tracker.models import SourceItem, StoryVersion
from tests.regression import e11_replay as e11
from tests.regression.rebuild import load_json

import scripts.record_e11 as record_e11

NOW = datetime(2026, 10, 26, 22, tzinfo=timezone.utc)
ANCHOR = "The excitement around Moderna’s cancer vaccine is cooling. Here’s why."


class _Scripted:
    logs_attempts = True

    def __init__(self, handler):
        self.handler = handler
        self.calls = []
        self.model = "fake"

    def complete(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(
            content=self.handler(kwargs),
            input_tokens=1,
            output_tokens=1,
            cached_tokens=0,
        )


def _draft(action, headline, body):
    return json.dumps(
        {
            "action": action,
            "headline": headline,
            "deck": "",
            "body": body,
            "why_it_matters": "",
            "reason": "",
        },
        ensure_ascii=False,
    )


def test_e11_pattern_flags_the_published_headline():
    """禁止樣式抓得到 10/27 刊出的錯標題，也放過沒有「2027 年申請」的標題。"""
    headline = next(
        article["headline"]
        for article in load_json("1027_edition.json")["articles"]
        if "莫德納" in article["headline"]
    )
    assert e11.headline_violations(headline)
    assert not e11.headline_violations("莫德納癌症疫苗熱度降溫")


def test_copy_editor_can_clear_a_bad_moderna_headline(session):
    """沒有錄音也能確認路徑：記者草稿踩線時，文稿編輯 CHALLENGE 會交回記者修稿。"""
    session.add(
        SourceItem(
            id=2736,
            source_id="marketwatch-top",
            section="finance",
            tier="T2",
            item_key="2736",
            url="https://www.marketwatch.com/story/moderna",
            canonical_url="https://www.marketwatch.com/story/moderna",
            title=ANCHOR,
            summary="Investors had high expectations around the Phase 3 data.",
            lang="en",
            published_at=NOW,
            first_seen_at=NOW,
        )
    )
    session.flush()
    evidence = [
        EvidenceItem(
            outlet="marketwatch.com",
            source_id="marketwatch-top",
            source_name="MarketWatch",
            tier="T2",
            lang="en",
            title=ANCHOR,
            summary="Investors had high expectations around the Phase 3 data.",
            url="https://www.marketwatch.com/story/moderna",
            published_at="2026-10-26T21:50+08:00",
            item_id=2736,
        )
    ]
    spec = {
        "keeper_cluster_id": 1,
        "merged_cluster_ids": [],
        "section": "world",
        "kind": "single_source",
        "score": 0,
        "evidence_item_ids": [2736],
        "anchor_item_id": 2736,
    }

    def handler(kwargs):
        system = kwargs["system"]
        if "文稿編輯" in system:
            return json.dumps(
                {
                    "action": "CHALLENGE",
                    "problem": "COPY",
                    "detail": "標題把審查寫成申請",
                    "required_action": "標題不要寫 2027 年申請",
                },
                ensure_ascii=False,
            )
        content = kwargs["messages"][0]["content"]
        if "CHALLENGE" in content:
            return _draft(
                "REVISE",
                "莫德納癌症疫苗熱度降溫",
                "投資人對實驗性癌症治療的期待降溫。[S1]",
            )
        return _draft(
            "DRAFT", "莫德納拼2027年申請FDA", "投資人對實驗性癌症治療的期待降溫。[S1]"
        )

    client = _Scripted(handler)
    version = e11.run_roles(session, client, spec=spec, evidence=evidence)
    systems = [call["system"] for call in client.calls]
    assert any("記者" in system for system in systems)
    assert any("文稿編輯" in system for system in systems)
    assert not any("查核員" in system for system in systems)
    versions = session.scalars(
        select(StoryVersion).order_by(StoryVersion.version)
    ).all()
    assert e11.headline_violations(versions[0].headline)
    assert version.headline == "莫德納癌症疫苗熱度降溫"
    assert not e11.headline_violations(version.headline)


def test_check_without_fixture_does_not_call_codex(monkeypatch, tmp_path):
    monkeypatch.setattr(e11, "RECORDS", tmp_path / "1027_e11_records.json")
    monkeypatch.setattr(e11, "EVIDENCE", tmp_path / "1027_e11_evidence.json")
    assert record_e11.main(["--check"]) == 2
    assert not (tmp_path / "1027_e11_records.json").exists()


def test_live_refuses_a_database_outside_data_work(monkeypatch, tmp_path):
    monkeypatch.setattr(record_e11, "WORK_DB", tmp_path / "1027_e11.db")
    with pytest.raises(SystemExit, match="data/work"):
        record_e11.main(["--live"])


def test_recorder_targets_the_single_source_marketwatch_story(tmp_path):
    """錄音選的是回歸重編那則，不是 10/27 刊出時併進去的 STAT 稿。"""
    story = e11.prepare_story(tmp_path / "1027_e11.db")
    json.dumps(story)  # --live 要原樣寫進 evidence fixture
    assert story["anchor_item_id"] == 2736
    assert story["member_ids"] == [2736]
    assert story["source_ids"] == ["marketwatch-top"]
    assert story["section"] == "world"
    assert story["kind"] == "single_source"
    assert story["original_section"] == "finance"
    assert story["stat_item_id"] == 3875
    assert story["stat_same_cluster"] is False
    assert "不併" in story["note"]

    engine = create_engine("sqlite://", future=True)
    from reddit_tracker.models import Base

    Base.metadata.create_all(engine)
    with Session(engine) as session:
        e11.insert_source_items(session, story["source_items"])
        reloaded = e11.reloaded_evidence(session, story)
    engine.dispose()
    assert [
        (item.title, item.summary, item.display_name, item.source_id)
        for item in reloaded
    ] == [
        (
            item["title"],
            item["summary"],
            EvidenceItem(**item).display_name,
            item["source_id"],
        )
        for item in story["evidence"]
    ]


def test_e11_replay_uses_the_recording_when_present(session):
    """有 fixture 才重播。沒有就 skip，不把「還沒錄」說成通過。"""
    if not e11.RECORDS.is_file() or not e11.EVIDENCE.is_file():
        pytest.skip(e11.missing_recording_message())
    version, client, rows, used_roles = e11.replay_recorded(session)
    assert not client.misses
    assert 1 <= len(rows) <= e11.MAX_ATTEMPTS
    assert all(row["provider"] == "codex" and row["ok"] for row in rows)
    assert {"reporter", "copy_editor"} <= set(used_roles)
    assert version.headline
    assert not e11.headline_violations(version.headline)

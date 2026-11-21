"""MAS_NOISE_CHECK：稿件欄位混進模型雜訊就 system HOLD；預設關閉時行為不變。"""
import json
from collections import Counter
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from reddit_tracker.config import get_settings
from reddit_tracker.daily.mas.orchestrator import run_mas
from reddit_tracker.daily.store import latest_version
from reddit_tracker.daily.view import build_edition_view
from reddit_tracker.models import AgentMessage, Story
from tests.test_mas_steps import DAY, NOW, SECTIONS, Scripted, _checker, _item, _registry, _snapshot

# 11/15 69855 的原文片段
NOISE = "許淑華與蔣萬安的攻防牽動選情。[S1]内 wait stop wrong? final already text need close proper. } I'm generating need valid JSON exact."


def _run(session, noisy_index: int):
    raw = []
    for i, section in enumerate(SECTIONS):
        for j in range(5):
            item = _item(session, f"武契奇事件{i}-{j}", "國會選舉結果", url=f"https://www.cna.com.tw/n{i}/{j}")
            raw.append(_snapshot([item.id], i * 10 + j, section=section, score=100 - j))
    reporter = {"n": 0}

    def handler(kw):
        system = kw["system"]
        if "分版主編" in system:
            data = json.loads(kw["messages"][0]["content"])
            return json.dumps({"pitches": [{"story_id": p["story_id"], "angle": "國會", "priority": "front"}
                                           for p in data["candidates"]]})
        if "總編輯" in system:
            data = json.loads(kw["messages"][0]["content"])
            ids = [p["story_id"] for p in data["front"]][:6]
            return json.dumps({"lead": ids[0], "second": ids[1:5], "briefs": ids[5:],
                               "links": [], "reasons": [], "dropped": []})
        if "記者" in system:
            reporter["n"] += 1
            why = NOISE if reporter["n"] == noisy_index else "國會結構改變"
            return json.dumps({"action": "DRAFT", "headline": "武契奇選舉", "deck": "國會大選後",
                               "body": "國會選舉結果。[S1]", "why_it_matters": why}, ensure_ascii=False)
        return _checker("OK", "")

    result = run_mas(session, edition_date=DAY, snapshot=SimpleNamespace(candidates=raw), registry=_registry(),
                     client=Scripted(handler), now=NOW)
    noisy = [s for s in session.scalars(select(Story).where(Story.edition_date == DAY))
             if (v := latest_version(session, s.id)) is not None and "wait stop" in (v.why_it_matters or "")]
    assert len(noisy) == 1
    return result, noisy[0]


@pytest.fixture
def no_approval(monkeypatch):
    """production 11/14 起關閉人工核可：發行時只扣 HOLD 的稿。"""
    monkeypatch.setenv("DAILY_REQUIRE_APPROVAL", "false")
    monkeypatch.delenv("MAS_NOISE_CHECK", raising=False)
    get_settings.cache_clear()
    yield monkeypatch
    get_settings.cache_clear()


@pytest.fixture
def noise_check(no_approval):
    no_approval.setenv("MAS_NOISE_CHECK", "true")
    get_settings.cache_clear()
    yield


def test_default_off_publishes_noisy_story_unchanged(session, no_approval):
    assert get_settings().mas_noise_check is False
    result, story = _run(session, noisy_index=3)
    assert result.noise_log == {}
    assert latest_version(session, story.id).status == "checked"
    view = build_edition_view(session, DAY, "mas", SECTIONS, for_publish=True)
    assert Counter(a.display for a in view.articles)["full"] == 12
    assert len({a.story_id for a in view.articles if a.display == "full"}) == 12


def test_noise_check_holds_only_the_noisy_story(session, noise_check):
    result, story = _run(session, noisy_index=3)
    assert set(result.noise_log) == {story.id}
    assert set(result.noise_log[story.id]) == {"why_it_matters"}
    version = latest_version(session, story.id)
    assert version.status == "hold"
    holds = session.scalars(select(AgentMessage).where(
        AgentMessage.type == "HOLD", AgentMessage.story_id == story.id)).all()
    assert len(holds) == 1 and holds[0].sender_role == "system" and holds[0].target_version == version.version
    assert "wait stop wrong? final already text need close proper." in holds[0].payload["noise"]["why_it_matters"]
    view = build_edition_view(session, DAY, "mas", SECTIONS, for_publish=True)
    held = [a for a in view.articles if a.story_id == story.id]
    assert held and all(a.withheld and a.withheld_reason == "hold" and a.why_it_matters == "" for a in held)
    assert len({a.story_id for a in view.articles if a.display == "full"}) == 11


def test_noise_check_adds_no_model_calls_and_is_idempotent(session, noise_check):
    from reddit_tracker.daily.mas.orchestrator import Clock, MasResult, noise_hold

    result, story = _run(session, noisy_index=1)
    again = noise_hold(session, edition_date=DAY, story_ids=[story.id], clock=Clock(NOW), result=MasResult())
    assert again == {}  # 已經 HOLD 的稿不再發第二則
    holds = session.scalars(select(AgentMessage).where(AgentMessage.type == "HOLD", AgentMessage.story_id == story.id))
    assert len(holds.all()) == 1

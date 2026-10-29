"""PR #1 semantics: shared 12-story layout, preserved inner pages and isolated snapshots."""
from collections import Counter
from types import SimpleNamespace
import json

from sqlalchemy import select

from reddit_tracker.daily.mas.orchestrator import run_mas
from reddit_tracker.daily.view import build_edition_view
from reddit_tracker.daily.render import render_html
from reddit_tracker.models import PagePlan
from tests.test_mas_steps import DAY, NOW, SECTIONS, Scripted, _item, _registry, _snapshot, _checker


def test_three_editor_calls_twelve_stories_and_eic_preserves_inner_pages(session):
    raw = []
    for i, section in enumerate(SECTIONS):
        for j in range(5):
            item = _item(session, f"武契奇事件{i}-{j}", "國會選舉結果", url=f"https://www.cna.com.tw/{i}/{j}")
            raw.append(_snapshot([item.id], i * 10 + j, section=section, score=100-j))
    def handler(kw):
        if "分版主編" in kw["system"]:
            data = json.loads(kw["messages"][0]["content"])
            return json.dumps({"pitches": [{"story_id": p["story_id"], "angle": "國會", "priority": "front"}
                                           for p in data["candidates"]]})
        if "總編輯" in kw["system"]:
            data = json.loads(kw["messages"][0]["content"])
            ids = [p["story_id"] for p in data["front"]][:6]
            return json.dumps({"lead": ids[0], "second": ids[1:5], "briefs": ids[5:],
                               "links": [], "reasons": [{"why": "容量六則"}], "dropped": []})
        if "記者" in kw["system"]:
            return json.dumps({"action": "DRAFT", "headline": "武契奇選舉", "body": "國會選舉結果。[S1]"})
        return _checker("OK", "")
    client = Scripted(handler)
    run_mas(session, edition_date=DAY, snapshot=SimpleNamespace(candidates=raw), registry=_registry(), client=client, now=NOW)
    assert sum("分版主編" in c["system"] for c in client.calls) == 3
    assert sum("記者" in c["system"] for c in client.calls) == 12
    plan = session.scalar(select(PagePlan).order_by(PagePlan.plan_version.desc()))
    assert {k: len(v) for k, v in plan.slots["sections"].items()} == {s: 4 for s in SECTIONS}
    view = build_edition_view(session, DAY, "mas", SECTIONS)
    assert len({a.story_id for a in view.articles}) == 12
    assert sum(a.is_front for a in view.articles) == 6
    assert Counter(a.display for a in view.articles)["full"] == 12
    html = render_html(view)
    assert html.count('class="link-only"') == 6


def test_copy_editor_challenge_goes_back_to_reporter_and_is_rechecked(session):
    """文稿編輯只能提異議：交回記者修稿（v2），程式重驗後才回到 checked；不能自己改稿。"""
    from reddit_tracker.models import AgentMessage, StoryVersion

    raw = []
    for i, section in enumerate(SECTIONS):
        item = _item(session, f"武契奇事件{i}", "國會選舉結果", url=f"https://www.cna.com.tw/c{i}")
        raw.append(_snapshot([item.id], 100 + i, section=section, score=50 - i))
    copy_calls = {"n": 0}

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
        if "文稿編輯" in system:
            copy_calls["n"] += 1
            if copy_calls["n"] == 1:
                return json.dumps({"action": "CHALLENGE", "detail": "標題說選舉、正文說國會，用語不一"})
            return json.dumps({"action": "OK", "detail": ""})
        if "記者" in system:
            if "CHALLENGE" in kw["messages"][0]["content"]:
                return json.dumps({"action": "REVISE", "headline": "武契奇國會選舉", "body": "國會選舉結果。[S1]"})
            return json.dumps({"action": "DRAFT", "headline": "武契奇選舉", "body": "國會選舉結果。[S1]"})
        return _checker("OK", "")

    client = Scripted(handler)
    run_mas(session, edition_date=DAY, snapshot=SimpleNamespace(candidates=raw), registry=_registry(),
            client=client, now=NOW)

    challenge = session.scalar(select(AgentMessage).where(
        AgentMessage.sender_role == "copy_editor", AgentMessage.type == "CHALLENGE"))
    assert challenge is not None and challenge.status == "handled"
    story_id = challenge.story_id
    versions = session.scalars(select(StoryVersion).where(StoryVersion.story_id == story_id)
                               .order_by(StoryVersion.version)).all()
    assert [v.version for v in versions][-1] == 2
    assert versions[-1].caused_by_message_id == challenge.id and versions[-1].status == "checked"
    assert versions[-1].headline == "武契奇國會選舉"
    done = session.scalar(select(AgentMessage).where(
        AgentMessage.story_id == story_id, AgentMessage.type == "REVISION_DONE"))
    assert done is not None and done.sender_role == "reporter"
    # 文稿編輯沒有寫入稿件的權限：v2 是記者寫的
    assert versions[-1].sender == "agent"


def test_quota_degradation_order_and_no_duplicate_mas_articles(daily_env, monkeypatch):  # noqa: F811
    from reddit_tracker.daily import run
    from reddit_tracker.models import DailyEdition
    class EmptyGuard:
        daily_limit = 40
        def used(self, model):
            return 40
    class NoCalls:
        guard = EmptyGuard()
        model = "gpt-test"
        def complete(self, **kw):
            raise AssertionError("exhausted guard must not invoke a model")
    # plan_edition can use fake desk; MAS receives only the exhausted client.
    daily_env.writer.client = NoCalls()
    from tests.test_daily import EDITION, NOW as daily_now
    eid = run.prepare_daily(EDITION, now=daily_now, mode="mas")
    edition = daily_env.session.get(DailyEdition, eid)
    assert len(edition.articles) == len({a.cluster_id for a in edition.articles})
    assert edition.stats["degraded"] == ["copy_editor", "fact_checker", "reporter"]
    assert sum(edition.stats["sections"].values()) == len(edition.articles)


# Reuse an existing isolated environment, never a real DB/client.
from tests.test_daily import daily_env  # noqa: E402, F401

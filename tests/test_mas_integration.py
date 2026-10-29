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
    # 內版連結顯示稿件標題，不把分版主編的內部角度（angle）印給讀者
    assert html.count(">武契奇選舉</a>（見頭版）") == 6 and ">國會</a>" not in html


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


def test_t1_decision_only_moves_the_contested_story():
    """10/30 真 Codex 的 T1 只回了被搶的那一篇；頭版其他 5 則不能因此消失。"""
    from reddit_tracker.daily.mas.orchestrator import _Decision, merge_t1_decision

    front = [1, 2, 5, 6, 7, 8]
    only_lead = _Decision(lead=1, links=[{"story_id": 1, "section": "tech", "label": "x"}])
    merged = merge_t1_decision(front, 1, only_lead)
    assert [merged.lead, *merged.second, *merged.briefs] == front and merged.links == only_lead.links
    promoted = merge_t1_decision(front, 7, _Decision(lead=7))
    assert promoted.lead == 7 and promoted.second == [1, 2, 5, 6] and promoted.briefs == [8]
    dropped = merge_t1_decision(front, 2, _Decision(lead=None))
    assert [dropped.lead, *dropped.second, *dropped.briefs] == [1, 5, 6, 7, 8]


def test_t3_empty_front_decision_is_rejected(session):
    """10/30 真 Codex 的 T3 回了「暫不排版」（lead=null）；程式要拒絕，不能寫出空頭版。"""
    from reddit_tracker.daily.mas.orchestrator import MasResult, Pitch, _resolve_t3
    from reddit_tracker.daily.mas.protocol import Clock
    from reddit_tracker.daily.store import add_page_plan, add_story, write_story_version
    from reddit_tracker.models import AgentMessage

    ids = []
    for i in range(8):
        story = add_story(session, edition_date=DAY, run_variant="mas", spec={
            "keeper_cluster_id": 500 + i, "merged_cluster_ids": [], "section": SECTIONS_LIST[i % 3],
            "kind": "report", "score": 10 - i})
        write_story_version(session, story_id=story.id, run_variant="mas", expected_latest=0,
                            headline=f"稿{i}", body="正文。", now=NOW, status="checked")
        ids.append(story.id)
    add_page_plan(session, edition_date=DAY, run_variant="mas", now=NOW, slots={
        "front": {"lead": ids[0], "second": ids[1:5], "briefs": ids[5:6]},
        "sections": {s: [{"story_id": i, "display": "full"} for i in ids if ids.index(i) % 3 == k]
                     for k, s in enumerate(SECTIONS_LIST)}})
    front = [Pitch(section=SECTIONS_LIST[k % 3], story_id=i, angle="", priority="front") for k, i in enumerate(ids)]
    empty = json.dumps({"lead": None, "second": [], "briefs": [], "links": [], "dropped": [],
                        "reasons": [{"story_id": ids[0], "why": "暫不排版"}]})
    seen = []

    def handler(kw):
        seen.append(json.loads(kw["messages"][0]["content"]))
        return empty

    result = MasResult()
    _resolve_t3(session, edition_date=DAY, front=front, client=Scripted(handler), clock=Clock(NOW),
                hold_ids=set(), result=result)
    decision = session.scalar(select(AgentMessage).where(AgentMessage.type == "DECISION"))
    assert decision.status == "rejected" and "頭版沒有主稿" in decision.payload["program_reason"]
    assert result.page_plan_ids == [] and session.scalar(select(PagePlan).order_by(
        PagePlan.plan_version.desc())).slots["front"]["lead"] == ids[0]
    # 總編看得到標題，才判斷得了（真跑那次只給 story_id，模型說缺少識別）
    assert seen[0]["candidates"][0]["headline"] == "稿0" and "hold" in seen[0]["candidates"][0]


SECTIONS_LIST = list(SECTIONS)


def test_recorded_live_t1_t3_decisions_follow_the_rules():
    """10/30 在 data/work/1027_t1t3.db 用真 Codex 錄的兩個總編決定（scripts/verify_t1_t3.py），離線檢查。"""
    from pathlib import Path

    from reddit_tracker.daily.mas.orchestrator import _Decision, _decision_problems, merge_t1_decision

    rows = json.loads((Path(__file__).parent / "regression/fixtures/1027_t1t3_records.json").read_text())
    assert len(rows) == 2 and all(r["ok"] and r["role"] == "eic" for r in rows)
    assert all(r["model_version"].startswith("gpt-6.1-sol | codex-cli") for r in rows)
    decisions = [_Decision.model_validate(json.loads(r["response_text"])) for r in rows]
    t1 = next(d for d in decisions if d.links)
    t3 = next(d for d in decisions if not d.links)
    # T1：巴西主稿歸國際版，科技版用連結；併回原頭版後 6 則都在
    assert t1.links[0]["section"] == "tech" and t1.reasons
    merged = merge_t1_decision([1, 2, 5, 6, 7, 8], t1.lead, t1)
    assert len([merged.lead, *merged.second, *merged.briefs]) == 6
    # T3：8 則提案選剛好 6 則，入選與落選都有理由
    chosen = [t3.lead, *t3.second, *t3.briefs]
    assert len(chosen) == 6 and not _decision_problems(t3, set(), min_front=6)
    assert len(t3.reasons) == 6 and len(t3.dropped) == 2 and all(d.get("why") for d in t3.dropped)

"""回放時間線（3D 辦公室）、訊息與 llm_records 的連結、訊息結案、真實時鐘、前台標示。"""
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from sqlalchemy import select

from reddit_tracker.daily.mas.orchestrator import run_mas
from reddit_tracker.daily.mas.protocol import Clock, wall_clock
from reddit_tracker.daily.office_page import render_office
from reddit_tracker.daily.render import render_html
from reddit_tracker.daily.replay import build_replay
from reddit_tracker.daily.view import build_edition_view
from reddit_tracker.models import AgentMessage, LLMRecord
from tests.test_mas_steps import DAY, NOW, SECTIONS, Scripted, _checker, _item, _registry, _snapshot


def _run(session, *, inject: str = "國會選舉結果"):
    raw = []
    for i, section in enumerate(SECTIONS):
        item = _item(session, f"武契奇事件{i}", inject, url=f"https://www.cna.com.tw/r{i}")
        raw.append(_snapshot([item.id], 300 + i, section=section, score=50 - i))
    copy_calls = {"n": 0}

    def handler(kw):
        system = kw["system"]
        if "分版主編" in system:
            data = json.loads(kw["messages"][0]["content"])
            return json.dumps({"pitches": [{"story_id": p["story_id"], "angle": "國會", "priority": "front"}
                                           for p in data["candidates"]]})
        if "總編輯" in system:
            data = json.loads(kw["messages"][0]["content"])
            ids = [p["story_id"] for p in data["candidates"]][:6]
            return json.dumps({"lead": ids[0], "second": ids[1:5], "briefs": ids[5:], "links": [],
                               "reasons": [{"story_id": ids[0], "why": "最重要"}], "dropped": []})
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

    run_mas(session, edition_date=DAY, snapshot=SimpleNamespace(candidates=raw), registry=_registry(),
            client=Scripted(handler), now=NOW)


def test_messages_link_to_llm_records_and_are_settled(session):
    """手冊 6.3：llm_call_id 對到 llm_records；處理完的訊息不留在 pending。"""
    _run(session)
    messages = session.scalars(select(AgentMessage).order_by(AgentMessage.id)).all()
    by_type = {}
    for m in messages:
        by_type.setdefault(m.type, []).append(m)
    roles = dict(session.execute(select(LLMRecord.id, LLMRecord.role)).all())
    assert all(roles[m.llm_call_id] == "section_editor" for m in by_type["PITCH"])
    assert all(roles[m.llm_call_id] == "eic" for m in by_type["DECISION"])
    copy = [m for m in by_type["CHALLENGE"] if m.sender_role == "copy_editor"]
    assert copy and roles[copy[0].llm_call_id] == "copy_editor"
    assert all(roles[m.llm_call_id] == "reporter" for m in by_type["REVISION_DONE"])
    # 程式自己發的放行沒有模型呼叫
    assert all(m.llm_call_id is None for m in by_type["RELEASE"])
    left = {m.type for m in messages if m.status == "pending"}
    assert left <= {"HOLD", "CHALLENGE"}, left
    assert all(m.status == "handled" for m in by_type["PITCH"] + by_type["RELEASE"] + by_type["PAGE_OBJECTION"])


def test_wall_clock_only_when_enabled():
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    clock = Clock(start)
    assert clock.tick() == start + timedelta(seconds=1)  # 重播、測試：每則 +1 秒
    with wall_clock():
        first, second = clock.tick(), clock.tick()
    assert second > first and abs(first - datetime.now(timezone.utc)) < timedelta(seconds=5)
    naive = Clock(datetime(2026, 1, 1))
    with wall_clock():
        assert naive.tick().tzinfo is None


def test_replay_timeline_tells_the_story_in_order(session):
    _run(session)
    data = build_replay(session, DAY, "mas")
    json.dumps(data)  # 純資料
    beats = data["beats"]
    assert data["timing"] == "recorded" and len(data["stories"]) == 3 and data["plans"]
    kinds = [(b["kind"], b.get("type")) for b in beats]
    for expected in [("message", "PITCH"), ("message", "RELEASE"), ("message", "PAGE_OBJECTION"),
                     ("message", "DECISION"), ("message", "CHALLENGE"), ("message", "REVISION_DONE"), ("plan", None)]:
        assert expected in kinds, expected
    phases = [b["phase"] for b in beats]
    assert phases.index("pitch") < phases.index("write") < phases.index("layout") < phases.index("copy")
    assert [b["i"] for b in beats] == list(range(len(beats)))
    # 每一次模型呼叫都有一步，附提示詞與回應
    llm = [b for b in beats if b["kind"] == "llm"]
    assert len(llm) == session.scalar(select(LLMRecord.id).order_by(LLMRecord.id.desc()))
    assert all(b["detail"]["prompt"] and b["detail"]["response"] for b in llm)
    # 文稿異議 → 記者改成 v2，附 diff；狀態跟著走
    challenge = next(b for b in beats if b.get("type") == "CHALLENGE")
    assert challenge["actor"] == "copy_editor" and challenge["walk"]
    revised = next(b for b in beats if b["kind"] == "llm" and b["actor"] == "reporter" and b["detail"].get("version") == 2)
    assert revised["i"] > challenge["i"] and revised["state"]["stories"]
    release = [b for b in beats if b.get("type") == "RELEASE"]
    assert all(b["actor"] == "checktool" and b["state"] for b in release)


def test_replay_of_an_empty_day_is_empty_but_valid(session):
    data = build_replay(session, DAY, "mas")
    assert data["stories"] == {} and data["plans"] == []
    assert all(b["kind"] in ("cluster", "snapshot") for b in data["beats"])


def test_office_page_embeds_data_safely(session):
    _run(session, inject="摘要</script><script>alert(1)</script>")
    html = render_office(session, DAY, "mas")
    assert "__REPLAY_JSON__" not in html and "__THREE_URL__" not in html and "__DATE__" not in html
    assert "</script><script>alert(1)" not in html  # 新聞內容關不掉資料標籤
    start = html.index('<script id="replay-data" type="application/json">') + len('<script id="replay-data" type="application/json">')
    data = json.loads(html[start:html.index("</script>", start)])
    assert data["date"] == DAY.isoformat() and data["beats"]
    assert f"/daily/{DAY.isoformat()}/newsroom?variant=mas" in html


def test_edition_page_shows_issue_tags_times_and_footer(session):
    _run(session)
    view = build_edition_view(session, DAY, "mas", SECTIONS)
    view.published_at = datetime(2026, 11, 12, 0, 35)  # SQLite 讀回來沒有時區，存的是 UTC
    view.issue_number = 17
    html = render_html(view)
    assert "第 17 期" in html and "2026-11-12 08:35 出刊" in html
    assert "依標題與摘要撰稿" in html
    assert "AI 撰稿 3 則" in html
    for article in view.articles:
        for source in article.sources:
            assert source["published_at"]

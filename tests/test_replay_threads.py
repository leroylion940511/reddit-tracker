"""回放頁 R1 稿件協商串、R2 角色泳道、R3 播放控制、R4 互動摘要卡。fixture 是 11/19 M 組真實的 build_replay 輸出。"""
import json
from pathlib import Path

from reddit_tracker.daily.office_page import render_office
from reddit_tracker.daily.replay import build_card, build_lanes, build_replay, build_threads
from tests.test_mas_steps import DAY
from tests.test_replay_office import _run

FIXTURE = Path(__file__).parent / "fixtures" / "replay" / "2026-11-19_mas.json"


def _threads():
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    return data, build_threads(data["beats"])


def test_every_written_story_has_a_thread_in_time_order():
    data, threads = _threads()
    assert set(threads) == set(data["stories"])
    for thread in threads.values():
        order = [s["i"] for s in thread["steps"]]
        assert order == sorted(order)
        assert thread["steps"][0]["label"] == "提案"
        assert all(data["beats"][s["i"]]["at"] == s["at"] for s in thread["steps"])


def test_challenge_revision_release_chain_with_sender_receiver_and_timing():
    """GTA VI 那篇：查核員異議 → 記者修稿 v2 → 修稿完成（有 diff）→ 程式重驗放行。"""
    _, threads = _threads()
    thread = threads["86093"]
    labels = [s["label"] for s in thread["steps"]]
    assert labels == ["提案", "記者寫稿", "查核員判斷", "異議", "記者修稿", "修稿完成", "放行", "文稿編輯"]
    pitch, draft, _, challenge, revise, done, release, _ = thread["steps"]
    assert (pitch["actor"], pitch["to"]) == ("section_tech", "eic") and pitch["say"].startswith("想上頭版")
    assert (draft["to"], draft["version"], draft["secs"]) == ("fact_checker", 1, 11.2)
    assert (challenge["actor"], challenge["to"], challenge["objection"]) == ("fact_checker", "reporter", True)
    assert challenge["secs"] == 5.5  # 訊息出自查核員那次呼叫
    assert revise["version"] == 2 and done["diff"] and done["version"] == 2
    assert (release["actor"], release["type"]) == ("checktool", "RELEASE")
    assert {k: thread[k] for k in ("challenges", "revisions", "requests", "outcome")} == {
        "challenges": 1, "revisions": 1, "requests": 0, "outcome": "RELEASE"}


def test_no_problem_challenge_is_not_counted_and_failed_call_is_labelled():
    _, threads = _threads()
    lead = threads["86089"]  # 頭版主稿：版面要求修稿；文稿編輯看過沒問題
    assert "看過沒問題" in [s["label"] for s in lead["steps"]]
    assert (lead["challenges"], lead["requests"], lead["revisions"]) == (0, 1, 1)
    assert threads["86090"]["steps"][1]["label"] == "記者撰稿（呼叫失敗）"


def test_build_replay_and_office_page_carry_threads(session):
    _run(session)
    data = build_replay(session, DAY, "mas")
    assert set(data["threads"]) == set(data["stories"])
    challenged = [t for t in data["threads"].values() if t["challenges"]]
    assert challenged and any(s["type"] == "REVISION_DONE" for s in challenged[0]["steps"])
    html = render_office(session, DAY, "mas")
    assert '"threads"' in html and "threadNode" in html


# ── 回放頁 R2：角色泳道時序圖（`build_lanes`） ──

def test_lanes_cover_only_interactions_in_beat_order():
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    lanes = build_lanes(data["beats"], "mas")
    assert [lane["short"] for lane in lanes["lanes"]] == ["台編", "國編", "科編", "總編", "記者", "查核", "工具", "文稿", "版面"]
    events = lanes["events"]
    assert {e["kind"] for e in events} <= {"llm", "message", "approve"}
    assert all(e["actor"] != "pipeline" for e in events)  # M 組頁面不畫 P 組流水線
    assert [e["i"] for e in events] == sorted(e["i"] for e in events)
    lane_ids = {lane["id"] for lane in lanes["lanes"]}
    assert all(e["actor"] in lane_ids and (e["to"] is None or e["to"] in lane_ids) for e in events)
    pitches = [e for e in events if e["type"] == "PITCH"]
    assert len(pitches) == 3 and all(e["to"] == "eic" for e in pitches)
    challenges = {e["i"]: e["objection"] for e in events if e["type"] == "CHALLENGE"}
    assert sorted(challenges.values()) == [False, True, True]
    failed = [e for e in events if e["kind"] == "llm" and e["ok"] is False]
    assert len(failed) == 1 and failed[0]["actor"] == "reporter"


def test_pipeline_lanes_keep_the_pipeline_actor():
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    lanes = build_lanes(data["beats"], "pipeline")
    assert any(lane["id"] == "pipeline" for lane in lanes["lanes"])


def test_build_replay_and_office_page_carry_lanes(session):
    _run(session)
    data = build_replay(session, DAY, "mas")
    assert data["lanes"]["events"] and {e["i"] for e in data["lanes"]["events"]} <= {b["i"] for b in data["beats"]}
    html = render_office(session, DAY, "mas")
    assert 'data-tab="lanes"' in html and "buildLanes" in html


# ── 回放頁 R3：播放控制（只看互動、下一個異議、快捷鍵；純前端） ──

def test_office_page_has_playback_controls(session):
    _run(session)
    html = render_office(session, DAY, "mas")
    for needle in ('id="onlyact"', 'id="nextch"', "function skippable", "function nextObjection",
                   "'KeyC'", "'KeyI'", "'Digit4'", "params.get('only')"):
        assert needle in html, needle
    # 剛點過分頁按鈕（焦點在按鈕上）時 C／I／方向鍵要照樣有效，只有空白鍵留給按鈕
    assert "matches?.('input,select,summary')" in html
    assert "e.code === 'Space' && e.target.matches?.('button')" in html


# ── 回放頁 R4：本期互動摘要卡（`build_card`） ──

def test_card_counts_match_fixture_and_page_summary():
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    beats = data["beats"]
    lanes, threads = build_lanes(beats, "mas"), build_threads(beats)
    card = build_card(beats, lanes, threads)
    counts = card["counts"]
    assert counts["messages"] == data["summary"]["messages"] == 34  # PITCH 照篇數算，才會和 agent_messages 對得上
    assert counts["llm_calls"] == sum(data["summary"]["llm_calls"].values()) == 30
    assert {k: counts[k] for k in ("pitches", "challenges", "checks_ok", "requests", "page_objections",
                                   "revisions", "holds", "revised_stories", "revised_released", "llm_failed")} == {
        "pitches": 12, "challenges": 2, "checks_ok": 1, "requests": 1, "page_objections": 2,
        "revisions": 3, "holds": 0, "revised_stories": 3, "revised_released": 3, "llm_failed": 1}
    assert card["matrix"]["fact_checker"] == {"reporter": 2}
    assert sum(sum(row.values()) for row in card["matrix"].values()) == counts["messages"]
    reporter = card["roles"]["reporter"]
    assert (reporter["calls"], reporter["failed"], reporter["sent"]) == (16, 1, 3)
    assert counts["span_secs"] == 406


def test_build_replay_and_office_page_carry_card(session):
    _run(session)
    data = build_replay(session, DAY, "mas")
    counts = data["card"]["counts"]
    assert counts["messages"] == data["summary"]["messages"]
    assert counts["llm_calls"] == sum(data["summary"]["llm_calls"].values())
    html = render_office(session, DAY, "mas")
    assert 'data-tab="card"' in html and "function cardMarkdown" in html

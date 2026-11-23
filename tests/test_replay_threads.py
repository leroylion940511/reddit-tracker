"""回放頁 R1：稿件協商串（`build_threads`）。fixture 是 11/19 M 組真實的 build_replay 輸出。"""
import json
from pathlib import Path

from reddit_tracker.daily.office_page import render_office
from reddit_tracker.daily.replay import build_replay, build_threads
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

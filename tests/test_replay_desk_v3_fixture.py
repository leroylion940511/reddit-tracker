"""desk-v3 高互動 demo 期（佇列第 13 項）：2026-11-24 M 組在 Lab 複本開 MAS_RICH_CONTEXT／MAS_OPEN_LAYOUT／
MAS_MORE_INTERACTION 跑出的真實 build_replay 輸出，和 11/19（開關全關）對照。只讀 fixture，不碰 DB。"""
import json
from pathlib import Path

from reddit_tracker.daily.replay import build_card, build_lanes, build_threads
from scripts.export_replay_fixture import compare_table

ROOT = Path(__file__).parent / "fixtures" / "replay"
DESK_V3 = ROOT / "2026-11-24_mas_desk_v3.json"
BASELINE = ROOT / "2026-11-19_mas.json"


def _load(path):
    data = json.loads(path.read_text(encoding="utf-8"))
    threads = build_threads(data["beats"])
    return data, threads, build_card(data["beats"], build_lanes(data["beats"]), threads)


def test_open_layout_sections_decided_by_editors_within_limits():
    data, threads, card = _load(DESK_V3)
    pitches = [b for b in data["beats"] if b.get("type") == "PITCH"]
    per_section = {b["actor"]: len(b["detail"]["pitches"]) for b in pitches}
    assert per_section == {"section_taiwan": 4, "section_world": 7, "section_tech": 6}
    assert all(1 <= n <= 8 for n in per_section.values()) and sum(per_section.values()) <= 18
    assert card["counts"]["stories"] == len(threads) == 17


def test_eic_revision_requests_go_to_reporter_and_are_rechecked():
    """C3：總編退稿 2 篇；108592 退稿後查核員重驗再異議、記者再修、最後放行。"""
    data, threads, card = _load(DESK_V3)
    assert card["matrix"]["eic"] == {"layout_editor": 1, "reporter": 2}
    assert card["counts"]["requests"] == 2
    labels = [s["label"] for s in threads["108592"]["steps"]]
    after = labels[labels.index("要求修稿"):]
    assert after[:3] == ["要求修稿", "記者修稿", "修稿完成"]
    assert "異議" in after and threads["108592"]["outcome"] == "RELEASE"


def test_threads_are_in_time_order_with_live_clock():
    """訊息與模型呼叫都是真實時間：整期在 15 分鐘內，協商串依時間排序。"""
    data, threads, card = _load(DESK_V3)
    assert data["timing"] == "recorded"
    assert 0 < card["counts"]["span_secs"] < 900
    for thread in threads.values():
        order = [s["i"] for s in thread["steps"]]
        assert order == sorted(order)


def test_more_interaction_than_baseline():
    _, _, base = _load(BASELINE)
    _, _, desk = _load(DESK_V3)
    for key in ("messages", "llm_calls", "challenges", "requests", "revisions"):
        assert desk["counts"][key] > base["counts"][key], key


def test_compare_table_lists_both_editions():
    base, _, _ = _load(BASELINE)
    desk, _, _ = _load(DESK_V3)
    table = compare_table(base, desk, "11/19", "11/24")
    assert table.splitlines()[0] == "| 項目 | 11/19 | 11/24 |"
    assert "| 訊息數 | 34 | 50 |" in table

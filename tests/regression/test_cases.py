"""手冊步驟 2 回歸集：第 4.2 節 15 個錯誤案例（E09 不是錯誤，另存供 T2 反駁用）。

每個案例檔 `cases/Exx.json` 的每個條件各是一個測試：
- `test_detects_original_error`：條件在 10/27 實際刊出的版面上必須抓到錯，證明條件有效。
- `test_rebuild`：在離線重編的 10/27 上必須通過。還沒修好的條件列在案例檔的 `xfail`
  裡，以 `xfail(strict=True)` 執行——修好後會變 XPASS 而失敗，提醒把那一條從 `xfail` 拿掉。
  到期（`due`）後仍掛 xfail 會讓 `test_overdue_cases_are_not_xfail` 失敗（手冊：到期後拿掉）。
"""

from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

from .checks import CONDITIONS, NEEDS_EVENT, referenced_titles, run_condition
from .rebuild import load_cases, load_items, norm_title

CASES = load_cases()
ERROR_CASES = [c for c in CASES if c["is_error"]]
# 手冊 4.2「回歸測試到期」欄
HANDBOOK_DUE = {
    "2026-11-04": {"E01", "E03", "E04", "E05", "E10", "E12", "E13", "E15", "E16"},
    "2026-11-08": {"E02", "E06", "E07"},
    "2026-11-15": {"E08", "E11", "E14"},
}
REQUIRED_KEYS = {"case_id", "edition", "is_error", "event_hint", "error", "stage", "fix", "expected", "due"}
DOC_KEYS = REQUIRED_KEYS | {"event_titles", "xfail", "market_close_date", "non_contradiction", "same_event_titles"}


def _conditions(case: dict) -> list[str]:
    return [key for key in CONDITIONS if key in case]


def _params(with_xfail: bool):
    params = []
    for case in ERROR_CASES:
        for key in _conditions(case):
            reason = case.get("xfail", {}).get(key)
            marks = [pytest.mark.xfail(strict=True, reason=reason)] if with_xfail and reason else []
            params.append(pytest.param(case, key, id=f"{case['case_id']}-{key}", marks=marks))
    return params


# ── 案例檔本身 ────────────────────────────────────────────────────────────


def test_case_files_cover_handbook_table():
    assert [c["case_id"] for c in CASES] == [f"E{i:02d}" for i in range(1, 17)]
    assert len(ERROR_CASES) == 15, "E09 不是錯誤，錯誤案例共 15 個"
    assert [c["case_id"] for c in CASES if not c["is_error"]] == ["E09"]
    due = {}
    for case in ERROR_CASES:
        due.setdefault(case["due"], set()).add(case["case_id"])
    assert due == HANDBOOK_DUE  # 11/04 九個、11/08 三個、11/15 三個
    assert next(c for c in CASES if c["case_id"] == "E09")["due"] is None


@pytest.mark.parametrize("case", CASES, ids=[c["case_id"] for c in CASES])
def test_case_schema(case):
    assert REQUIRED_KEYS <= case.keys()
    assert case["edition"] == "2026-10-27"
    unknown = case.keys() - DOC_KEYS - CONDITIONS.keys()
    assert not unknown, f"未知欄位：{unknown}"
    if case["is_error"]:
        date.fromisoformat(case["due"])
        assert _conditions(case), "錯誤案例至少要有一個可機器判斷的條件"
    assert set(case.get("xfail", {})) <= set(_conditions(case))
    if any(key in NEEDS_EVENT for key in _conditions(case)):
        assert case.get("event_titles")


def test_case_titles_exist_in_fixture():
    """案例引用的標題都是母本裡的真實標題（重編用的素材 fixture 找得到）。"""
    titles = {norm_title(item["title"]) for item in load_items()["items"]}
    missing = [(c["case_id"], t) for c in CASES for t in referenced_titles(c) if norm_title(t) not in titles]
    assert not missing


def test_overdue_cases_are_not_xfail():
    """手冊：還沒到期的標 xfail，到期後拿掉。"""
    today = datetime.now(ZoneInfo("Asia/Taipei")).date()
    overdue = [
        (c["case_id"], sorted(c["xfail"]))
        for c in ERROR_CASES
        if c.get("xfail") and date.fromisoformat(c["due"]) <= today
    ]
    assert not overdue, f"已到期但仍標 xfail：{overdue}"


# ── 條件 ──────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("case, key", _params(with_xfail=False))
def test_detects_original_error(published, case, key):
    """每個條件在 10/27 實際刊出的版面上都抓得到錯。"""
    assert run_condition(key, case, published), f"{case['case_id']} {key} 在原始版面上沒抓到錯"


@pytest.mark.parametrize("case, key", _params(with_xfail=True))
def test_rebuild(rebuilt, case, key):
    problems = run_condition(key, case, rebuilt)
    assert not problems, "\n".join(problems)


def test_e09_is_not_an_error(published):
    """E09 兩則數字分屬開盤與收盤，同在 10/27 的巴西事件裡；T2 實作後要能反駁「矛盾」。"""
    case = next(c for c in CASES if c["case_id"] == "E09")
    titles = case["non_contradiction"]["titles"]
    assert published.events_with(titles)
    assert all(any(norm_title(t) in s.members for s in published.events) for t in titles)
    assert "is_error" in case and case["is_error"] is False


def test_rebuild_replays_merges_without_real_llm(rebuilt):
    """重編版有跑到撰稿，而且所有撰稿請求都走 replay：有 miss 才會全部是模板稿。"""
    assert rebuilt.published
    assert all(s.writer == "template" for s in rebuilt.published) == bool(rebuilt.replay_misses)


def test_xfail_marks_are_strict():
    marks = [m for p in _params(with_xfail=True) for m in p.marks]
    assert marks and all(m.name == "xfail" and m.kwargs["strict"] is True for m in marks)

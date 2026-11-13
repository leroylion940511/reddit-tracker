"""實驗二：三組查核員開關、v1 共用、失敗就整組作廢、報告。不呼叫真模型。"""

from __future__ import annotations

import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from reddit_tracker.daily.mas.orchestrator import CHECKER_SCHEMA, DRAFT_SCHEMA
from reddit_tracker.eval import exp2
from reddit_tracker.eval.exp1_results import Pair
from reddit_tracker.llm.replay import ReplayResult
from reddit_tracker.models import Base
from tests.regression import rebuild

V1 = {"headline": "塞爾維亞國會大選 學運陣營席次過半", "deck": "", "body": "學運陣營在國會大選取得過半席次 [S1][S2]。", "why_it_matters": "政局轉向"}


class Scripted:
    """依 schema 回固定答案的假模型。"""

    model = "scripted"

    def __init__(self, checker_action="CHALLENGE", fail=False):
        self.checker_action = checker_action
        self.fail = fail
        self.misses = 0
        self.seen: list[str] = []

    def complete(self, **kwargs):
        schema = kwargs.get("json_schema")
        if self.fail:
            self.misses += 1
            raise RuntimeError("no recording")
        if schema == CHECKER_SCHEMA:
            self.seen.append("checker")
            return ReplayResult(json.dumps({"action": self.checker_action, "problem": "IRRELEVANT_SOURCE", "detail": "x", "required_action": "刪"}))
        assert schema == DRAFT_SCHEMA
        self.seen.append("reporter")
        return ReplayResult(json.dumps({
            "action": "REVISE", "headline": "模型寫的標題", "deck": "", "body": "修訂後只寫塞爾維亞大選 [S1]。", "why_it_matters": "x",
        }, ensure_ascii=False))


@pytest.fixture(scope="module")
def dev():
    engine = create_engine("sqlite://", future=True)
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add_all(rebuild._source_item(item) for item in rebuild.load_items()["items"])
        session.flush()
        cases = [c for c in rebuild.load_cases() if c["case_id"] in {"E01", "E02", "E03", "E04", "E05"}]
        return exp2.dev_cases(session, cases, {}, norm=rebuild.norm_title)


def _e01(dev):
    return next(case for case in dev if case.case_id == "E01")


def _clean(dev):
    """E01 拿掉無關來源，當成正常稿。"""
    case = _e01(dev)
    keep = [row for row in case.evidence if row["item_id"] not in case.wrong_item_ids]
    return exp2.Case("N-1", "normal", case.section, case.kind, keep, [], "正常稿")


def test_dev_cases_put_wrong_sources_last(dev):
    assert [case.case_id for case in dev] == ["E01", "E02", "E03", "E04", "E05"]
    for case in dev:
        ids = [row["item_id"] for row in case.evidence]
        assert case.wrong_item_ids and ids[-len(case.wrong_item_ids):] == case.wrong_item_ids
        assert ids[0] not in case.wrong_item_ids


def test_three_arms_on_e01(dev, tmp_path):
    case, drafts = _e01(dev), {"E01": V1}
    off = Scripted()
    a = exp2.run_arm("a", [case], drafts, off, tmp_path / "a.db")[0]
    assert (a.blocked, a.removed_item_ids, a.llm_calls, a.checker_calls) == (False, [], 0, 0)
    assert a.status == "checked" and a.versions == 1

    program = Scripted()
    b = exp2.run_arm("b", [case], drafts, program, tmp_path / "b.db")[0]
    assert b.blocked and b.removed_item_ids == case.wrong_item_ids
    assert program.seen == ["reporter"] and (b.llm_calls, b.checker_calls) == (1, 0)

    full = Scripted("CHALLENGE")
    c = exp2.run_arm("c", [case], drafts, full, tmp_path / "c.db")[0]
    assert c.blocked and full.seen == ["checker", "reporter"] and (c.llm_calls, c.checker_calls) == (2, 1)

    # 查核員 LLM 說是同一事件：程式點名的來源保留，這一組就沒擋下
    lenient = exp2.run_arm("c", [case], drafts, Scripted("OK"), tmp_path / "c2.db")[0]
    assert lenient.blocked is False and lenient.removed_item_ids == []


def test_normal_story_is_not_blocked_and_uses_saved_v1(dev, tmp_path):
    case = _clean(dev)
    client = Scripted()
    for arm in exp2.ARMS:
        outcome = exp2.run_arm(arm, [case], {"N-1": V1}, client, tmp_path / f"{arm}.db")[0]
        assert outcome.false_block is False and outcome.blocked is None and outcome.versions == 1
    assert client.seen == []  # v1 是存檔的，三組都沒再叫記者


def test_failed_call_voids_the_arm(dev, tmp_path):
    with pytest.raises(exp2.Exp2Error, match="這一組不算"):
        exp2.run_arm("b", [_e01(dev)], {"E01": V1}, Scripted(fail=True), tmp_path / "b.db")
    with pytest.raises(exp2.Exp2Error, match="先跑 draft"):
        exp2.run_arm("b", [_e01(dev)], {}, Scripted(), tmp_path / "b.db")


def test_draft_is_written_once_and_template_is_refused(dev, tmp_path):
    case, out = _e01(dev), tmp_path / "v1.json"
    client = Scripted()
    drafts = exp2.draft_all([case], client, tmp_path / "d.db", out)
    assert drafts["E01"]["headline"] == "模型寫的標題" and client.seen == ["reporter"]
    exp2.draft_all([case], client, tmp_path / "d.db", out)
    assert client.seen == ["reporter"]  # 已有 v1，不重寫
    with pytest.raises(exp2.Exp2Error, match="不是模型寫的"):
        exp2.draft_all([case], Scripted(fail=True), tmp_path / "d2.db", tmp_path / "other.json")


def test_holdout_pairs_take_test_false_merges_of_method_a():
    def pair(pid, split, final, a):
        return Pair(pid, split, "same", "both", a, False, final, "", final)

    pairs = [pair("T2", "test", "不是", True), pair("T1", "test", "不是", True), pair("T3", "test", "是", True),
             pair("T4", "test", "不是", False), pair("D1", "dev", "不是", True), pair("T5", "test", "不確定", True)]
    assert [p.pair_id for p in exp2.holdout_pairs(pairs)] == ["T1", "T2"]
    many = [pair(f"T{i:03d}", "test", "不是", True) for i in range(14)]
    assert len(exp2.holdout_pairs(many)) == exp2.MAX_HOLDOUT


def test_cases_round_trip_and_report(dev, tmp_path):
    cases = [_e01(dev), _clean(dev)]
    exp2.save_cases(cases, tmp_path / "cases.json")
    loaded = exp2.load_cases(tmp_path / "cases.json")
    assert [c.case_id for c in loaded] == ["E01", "N-1"] and loaded[0].items()[0].title
    with pytest.raises(exp2.Exp2Error, match="重複"):
        exp2.save_cases([cases[0], cases[0]], tmp_path / "dup.json")
    drafts = {"E01": V1, "N-1": V1}
    results = {arm: exp2.run_arm(arm, loaded, drafts, Scripted(), tmp_path / f"{arm}.db") for arm in ("a", "b")}
    text = exp2.render_report(results, loaded, generated="now", model_version="m", per_source=False, v1_calls=2, labels_note="標註說明。")
    assert "| (a) 全關 | 0/1 | 0/0 | 0/1 | 0（0） |" in text
    assert "| (b) 只開程式工具 | 1/1 | 0/0 | 0/1 | 1（0） |" in text
    assert "| (c) 程式＋LLM | 還沒跑 |" in text
    assert "正常稿是 1 篇" in text and "標註說明。" in text

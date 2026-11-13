"""實驗一結果計算：統計量對已知數值、輸入檢查、報告內容。"""

from __future__ import annotations

import pytest

from reddit_tracker.eval.exp1_results import (
    Exp1InputError, Pair, agreement, bootstrap_f1, build_pairs, cohen_kappa, confusion,
    mcnemar_a_vs_c, mcnemar_exact, render_report, wilson,
)


def _pair(i, final, a, c, *, kind="same", split="test", label_b=""):
    return Pair(f"T{i:03d}", split, kind, "both", a, c, final, label_b, final, f"標題一 {i}", f"標題二 {i}")


def test_handbook_example():
    """手冊 8.1 的計算例子：TP=17、FN=3、FP=1、TN=29。"""
    pairs = (
        [_pair(i, "是", True, True) for i in range(17)]
        + [_pair(100 + i, "是", False, False) for i in range(3)]
        + [_pair(200, "不是", True, True)]
        + [_pair(300 + i, "不是", False, False) for i in range(29)]
    )
    c = confusion(pairs, "A")
    assert (c.tp, c.fp, c.fn, c.tn) == (17, 1, 3, 29)
    assert round(c.precision, 2) == 0.94 and round(c.recall, 2) == 0.85
    assert round(c.f1, 2) == 0.89 and round(c.false_merge_rate, 3) == 0.033
    low, high = bootstrap_f1(pairs, "A")
    assert low < c.f1 < high and bootstrap_f1(pairs, "A") == (low, high)  # 固定種子，重跑相同


def test_wilson_matches_reference_values():
    # statsmodels proportion_confint(17, 20, method="wilson") → (0.6396, 0.9476)
    low, high = wilson(17, 20)
    assert round(low, 4) == 0.6396 and round(high, 4) == 0.9476
    assert wilson(0, 0) is None
    assert wilson(0, 10)[0] == 0.0 and wilson(10, 10)[1] == pytest.approx(1.0)


def test_mcnemar_exact_matches_binomial():
    assert mcnemar_exact(0, 0) == 1.0
    assert round(mcnemar_exact(1, 9), 5) == 0.02148  # 2 × (1 + 10) / 1024
    assert mcnemar_exact(5, 5) == 1.0
    pairs = [_pair(1, "是", True, False), _pair(2, "不是", True, False), _pair(3, "不是", True, False)]
    assert mcnemar_a_vs_c(pairs)[:2] == (1, 2)


def test_kappa_and_unsure_folding():
    assert cohen_kappa(["是", "是", "不是", "不是"], ["是", "不是", "不是", "不是"]) == pytest.approx(0.5)
    assert cohen_kappa(["是"] * 3, ["是"] * 3) is None
    pairs = [
        Pair("T1", "test", "same", "both", True, True, "不確定", "不是", "不是"),
        Pair("T2", "test", "same", "both", True, True, "是", "是", "是"),
        Pair("T3", "test", "same", "both", True, True, "是", "", "是"),
    ]
    result = agreement(pairs)
    assert (result["n"], result["agree"]) == (2, 2)


def test_unsure_is_excluded_then_counted_both_ways():
    pairs = [_pair(1, "不確定", True, False), _pair(2, "是", True, True)]
    assert confusion(pairs, "A").tp == 1
    assert confusion(pairs, "A", "yes").tp == 2
    assert confusion(pairs, "A", "no").fp == 1


def _rows():
    key = [
        {"pair_id": "D1", "split": "dev", "kind": "same", "stratum": "both", "a_merged": "True", "c_merged": "True", "b_double": "True"},
        {"pair_id": "T1", "split": "test", "kind": "cross", "stratum": "only_a", "a_merged": "True", "c_merged": "False", "b_double": "True"},
        {"pair_id": "T2", "split": "test", "kind": "same", "stratum": "neither", "a_merged": "False", "c_merged": "False", "b_double": "False"},
    ]
    a = [{"pair_id": pid, "標題 1": "甲", "標題 2": "乙", "判斷": label} for pid, label in (("D1", "是"), ("T1", "是"), ("T2", "不是"))]
    b = [{"pair_id": "D1", "判斷": "是"}, {"pair_id": "T1", "判斷": "不是"}]
    return key, a, b


def test_disagreement_needs_a_final_answer():
    key, a, b = _rows()
    with pytest.raises(Exp1InputError, match="T1"):
        build_pairs(key, a, b)
    pairs = build_pairs(key, a, b, [{"pair_id": "T1", "final": "不是"}])
    by_id = {p.pair_id: p for p in pairs}
    assert by_id["T1"].final == "不是" and by_id["T1"].label_a == "是"
    assert by_id["T2"].final == "不是" and by_id["T2"].label_b == ""


def test_bad_inputs_are_rejected():
    key, a, b = _rows()
    with pytest.raises(Exp1InputError, match="只能是"):
        build_pairs(key, [{**a[0], "判斷": ""}, *a[1:]], b)
    with pytest.raises(Exp1InputError, match="複標名單"):
        build_pairs(key, a, b[:1])
    with pytest.raises(Exp1InputError, match="對照表不同"):
        build_pairs(key, a[:2], b)


def test_report_uses_test_only_and_lists_c_errors():
    key, a, b = _rows()
    pairs = build_pairs(key, a, b, [{"pair_id": "T1", "final": "是"}])
    text = render_report(pairs, frozen_commit="abc123", annotators="A：甲；B：乙", generated="now")
    assert "abc123" in text and "A：甲；B：乙" in text
    assert "dev 1、test 2" in text
    assert "| T1 | 中英 | 是 | 沒合併 | 合併 |" in text  # C 漏併
    assert "D1" not in text
    assert "（待寫）" in text

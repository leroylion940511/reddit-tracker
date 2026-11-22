import json

import pytest

from reddit_tracker.daily.blind import mapping_digest
from reddit_tracker.eval.exp3 import (
    MANUAL_MARKER,
    Exp3Error,
    compute,
    count_items,
    parse_agy,
    render_report,
    sign_test,
)


def _item(number, *marked, guess="不知道"):
    row = {f"class{i}": int(i in marked) for i in range(1, 8)}
    return {"number": number, **row, "guess": guess, "reason": f"理由{number}"}


def _envelope(items, status="SUCCESS"):
    return json.dumps({"status": status, "response": json.dumps({"items": items}, ensure_ascii=False)})


def _mapping(day, variants, hold=()):
    return {
        str(n): {"edition_date": day, "variant": v, "section": "科技", "story_id": 100 + n, "hold": n in hold}
        for n, v in enumerate(variants, start=1)
    }


def test_parse_agy_reads_response_and_checks_numbers():
    labels = parse_agy(_envelope([_item(1, 1), _item(2, guess="P")]), expected=2)
    assert labels["1"]["class1"] == 1 and labels["1"]["class2"] == 0
    assert labels["2"]["guess"] == "P"
    with pytest.raises(Exp3Error, match="缺"):
        parse_agy(_envelope([_item(1)]), expected=2)
    with pytest.raises(Exp3Error, match="兩次"):
        parse_agy(_envelope([_item(1), _item(1)]), expected=1)
    with pytest.raises(Exp3Error, match="沒有成功"):
        parse_agy(_envelope([_item(1)], status="ERROR"), expected=1)


def test_count_items_counts_headers_only():
    assert count_items("# 盲計 2026-11-09｜共 2 篇\n\n#1\n版：台灣\n#2\n正文 #3 不算\n") == 2


def test_sign_test_exact_two_sided():
    assert sign_test([1] * 7)["p_value"] == pytest.approx(0.0156, abs=1e-4)
    result = sign_test([1, -1, 0, 0])
    assert (result["n"], result["p_value"]) == (2, 1.0)
    assert sign_test([0, 0])["p_value"] is None


def test_compute_and_render_per_day_and_total():
    mappings = {
        "2026-11-09": _mapping("2026-11-09", ["mas", "pipeline", "mas", "pipeline"], hold={3}),
        "2026-11-10": _mapping("2026-11-10", ["pipeline", "mas", "pipeline", "mas"]),
    }
    labels = {
        "2026-11-09": {"1": {"class1": 1, "guess": "M"}, "2": {"class2": 1, "class6": 1, "guess": "P"},
                       "3": {"class3": 1, "guess": "P"}, "4": {}},
        "2026-11-10": {"1": {"class7": 1}, "2": {}, "3": {}, "4": {"class5": 1, "reason": "a|b"}},
    }
    result = compute(labels, mappings)
    day1 = result["per_day"]["2026-11-09"]
    assert day1["main_errors"] == {"pipeline": 1, "mas": 2}
    assert result["total"]["main_errors"] == {"pipeline": 1, "mas": 3}
    assert result["total"]["errors"]["pipeline"][6] == 1  # 第 7 類不算主指標
    assert result["total"]["hold_blocked"]["main_errors"]["mas"] == 2
    assert result["sign"]["positive"] == 2
    report = render_report(result, "2026-11-23 07:00 台北", "agy")
    assert "| 2026-11-09 | 2 | 1 | 5 | 2 | 2 | 10 | 5 | 1 |" in report
    assert "M 每 10 篇有 7.5 個" in report and "P 有 2.5 個" in report
    assert "a／b" in report  # 表格裡的 | 要換掉
    assert MANUAL_MARKER not in report


def test_compute_requires_labels_for_every_day():
    with pytest.raises(Exp3Error, match="沒有 B 的結果"):
        compute({}, {"2026-11-09": _mapping("2026-11-09", ["mas"])})


def test_script_verifies_hash_and_keeps_manual(tmp_path, monkeypatch):
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
    import exp3_results

    day = "2026-11-09"
    root = tmp_path / "annotation"
    mapping = _mapping(day, ["mas", "pipeline"])
    (root / "_private" / day).mkdir(parents=True)
    (root / "_private" / day / "mapping.json").write_text(json.dumps(mapping), encoding="utf-8")
    (root / day).mkdir()
    (root / day / "mapping.sha256").write_text(mapping_digest(mapping) + "\n")
    (root / day / "blind.txt").write_text("#1\n#2\n", encoding="utf-8")
    raw = tmp_path / "raw"
    raw.mkdir()
    (raw / f"B_raw_{day}.json").write_text(_envelope([_item(1, 2), _item(2)]), encoding="utf-8")
    out = tmp_path / "exp3.md"
    out.write_text("舊\n" + MANUAL_MARKER + "\n## 手寫\n保留\n", encoding="utf-8")
    labels = tmp_path / "B_labels.json"
    args = ["--start", day, "--end", day, "--root", str(root), "--labels", str(labels),
            "--out", str(out), "--from-raw", str(raw), "--write"]
    assert exp3_results.main(args) == 0
    text = out.read_text(encoding="utf-8")
    assert text.startswith("# 實驗三結果") and text.endswith("## 手寫\n保留\n")
    assert json.loads(labels.read_text(encoding="utf-8"))[day]["1"]["class2"] == 1

    (root / day / "mapping.sha256").write_text("0" * 64 + "\n")
    with pytest.raises(SystemExit, match="不符"):
        exp3_results.main(args[:-3])

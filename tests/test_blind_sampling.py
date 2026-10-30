"""手冊 8.3 第 7 點的每日盲計抽樣與步驟 11 的匯出格式。不呼叫真 LLM。"""

from __future__ import annotations

import hashlib
import json
import re
from contextlib import contextmanager
from datetime import date, datetime, timezone

import pytest

from reddit_tracker.daily import run as run_module
from reddit_tracker.daily.blind import (
    BLIND_SEED,
    analyze_blind,
    export_blind_count,
    mapping_bytes,
    mapping_digest,
    private_mapping_path,
    sample_day,
    spot_check_sheet,
)
from reddit_tracker.daily.mas.protocol import post_message
from reddit_tracker.daily.store import MAS, PIPELINE, add_page_plan, add_story, hold_story, write_story_version
from reddit_tracker.models import SourceItem

DAY = date(2026, 11, 9)
OTHER_DAY = date(2026, 11, 10)
NOW = datetime(2026, 11, 8, 22, 0, tzinfo=timezone.utc)
SECTIONS = ("taiwan", "world", "tech")


def _source(session, n: int) -> int:
    url = f"https://www.cna.com.tw/{n}"
    row = SourceItem(
        source_id="cna", section="world", tier="T2", item_key=url, url=url, canonical_url=url,
        title=f"來源標題{n % 1000}", summary=f"來源摘要{n % 1000}", lang="zh-Hant", published_at=NOW, first_seen_at=NOW,
    )
    session.add(row)
    session.flush()
    return row.id


def _write(session, day, variant, keeper, *, body="正文 [1]。", status="checked", lead=False):
    story = add_story(session, edition_date=day, run_variant=variant, spec={
        "keeper_cluster_id": keeper, "merged_cluster_ids": [keeper + 1000], "section": SECTIONS[keeper % 3],
        "kind": "report", "score": 1,
    })
    write_story_version(
        session, story_id=story.id, run_variant=variant, expected_latest=0, headline=f"事件{keeper}標題",
        body=body, source_ids=[_source(session, day.toordinal() * 1000 + keeper * 10 + (variant == MAS))], status=status, now=NOW,
    )
    return story


def _edition(session, day, common: int, *, p_only=(), m_only=(), m_empty=()):
    """common 個兩組都有寫的事件，另外加只有一組寫的、M 只有空正文的。"""
    stories = {}
    for keeper in range(1, common + 1):
        stories[(PIPELINE, keeper)] = _write(session, day, PIPELINE, keeper)
        stories[(MAS, keeper)] = _write(session, day, MAS, keeper)
    for keeper in p_only:
        stories[(PIPELINE, keeper)] = _write(session, day, PIPELINE, keeper)
    for keeper in m_only:
        stories[(MAS, keeper)] = _write(session, day, MAS, keeper)
    for keeper in m_empty:
        stories[(PIPELINE, keeper)] = _write(session, day, PIPELINE, keeper)
        stories[(MAS, keeper)] = _write(session, day, MAS, keeper, body="  ")
    mas_ids = sorted(story.id for (variant, _), story in stories.items() if variant == MAS)
    if mas_ids:
        add_page_plan(session, edition_date=day, run_variant=MAS, now=NOW,
                      slots={"front": {"lead": mas_ids[0], "second": [], "briefs": []}, "sections": {}})
    return stories


def _keepers(day_sample):
    return [(item["story"].keeper_cluster_id, item["variant"]) for item in day_sample["items"]]


def test_eight_common_events_split_four_and_four_one_version_each(session):
    _edition(session, DAY, 12, p_only=(50, 51), m_only=(60,), m_empty=(70,))
    day = sample_day(session, DAY)
    assert day["common"] == 12  # 只有一組寫、M 正文空白的都不算
    keepers = [keeper for keeper, _ in _keepers(day)]
    assert len(keepers) == 8 and len(set(keepers)) == 8
    assert all(keeper <= 12 for keeper in keepers)
    variants = [variant for _, variant in _keepers(day)]
    assert variants.count(PIPELINE) == 4 and variants.count(MAS) == 4
    for item in day["items"]:
        assert item["story"].run_variant == item["variant"]


def test_same_day_is_reproducible_and_other_days_differ(session):
    _edition(session, DAY, 12)
    _edition(session, OTHER_DAY, 12)
    first = export_blind_count(session, [DAY])
    assert export_blind_count(session, [DAY]) == first
    assert _keepers(sample_day(session, DAY)) == _keepers(sample_day(session, DAY))
    assert _keepers(sample_day(session, DAY)) != _keepers(sample_day(session, OTHER_DAY))
    assert _keepers(sample_day(session, DAY, seed=BLIND_SEED + 1)) != _keepers(sample_day(session, DAY))


@pytest.mark.parametrize("common", [5, 6])
def test_fewer_than_eight_takes_all_and_halves(session, common):
    _edition(session, DAY, common)
    day = sample_day(session, DAY)
    variants = [variant for _, variant in _keepers(day)]
    assert sorted(keeper for keeper, _ in _keepers(day)) == list(range(1, common + 1))
    assert abs(variants.count(PIPELINE) - variants.count(MAS)) == common % 2
    text, mapping, _ = export_blind_count(session, [DAY])
    assert len(mapping) == common
    assert text.splitlines()[0] == f"# 盲計 2026-11-09｜共 {common} 篇"
    assert f"只有 {common} 篇" in text.splitlines()[1]


def test_zero_common_events_returns_nothing(session):
    _edition(session, DAY, 0, p_only=(1, 2), m_only=(3,))
    assert sample_day(session, DAY)["items"] == []
    assert export_blind_count(session, [DAY]) == ("", {}, mapping_digest({}))


def test_hold_story_is_sampled_with_pre_approval_version(session):
    stories = _edition(session, DAY, 1)
    m_story = stories[(MAS, 1)]
    post_message(session, run_variant=MAS, edition_date=DAY, sender="system", recipient="human", type="HOLD",
                 now=NOW, story_id=m_story.id, payload={"detail": "查核員 LLM 已停"})
    write_story_version(  # 真人之後改的版本不能進盲計
        session, story_id=m_story.id, run_variant=MAS, expected_latest=1, headline="真人改的標題",
        body="真人改的正文", now=NOW, sender="human",
    )
    for seed in range(BLIND_SEED, BLIND_SEED + 40):
        day = sample_day(session, DAY, seed=seed)
        if day["items"][0]["variant"] == MAS:
            break
    item = day["items"][0]
    assert item["variant"] == MAS and item["hold"] is True and item["version"].version == 1
    text, mapping, _ = export_blind_count(session, [DAY], seed=seed)
    assert mapping["1"]["hold"] is True and mapping["1"]["version"] == 1
    assert "真人改的" not in text and "hold" not in text.lower()


def test_human_hold_is_not_counted_as_mas_hold(session):
    stories = _edition(session, DAY, 1)
    m_story = stories[(MAS, 1)]
    post_message(session, run_variant=MAS, edition_date=DAY, sender="human", recipient="eic", type="HOLD",
                 now=NOW, story_id=m_story.id, payload={"by": "審核者"})
    hold_story(session, m_story.id)
    for seed in range(BLIND_SEED, BLIND_SEED + 40):
        day = sample_day(session, DAY, seed=seed)
        if day["items"][0]["variant"] == MAS:
            break
    assert day["items"][0]["hold"] is False


def test_blind_text_has_no_status_version_notes_or_group_clues(session):
    _edition(session, DAY, 10)
    text, mapping, _ = export_blind_count(session, [DAY])
    lowered = text.lower()
    for word in ("pipeline", "mas", "checked", "draft", "approved", "hold", "challenged", "review_notes",
                 "流水線", "編輯室", "影子", "版本"):
        assert word not in lowered
    assert not re.search(r"\bv\d", lowered)
    body = text.split("編號,")[0]
    assert "P" not in body and "M" not in body
    assert "[S1]" in text and "[1]" not in text
    assert sorted(mapping, key=int) == [str(n) for n in range(1, 9)]
    assert re.findall(r"^#(\d+)$", text, flags=re.M) == [str(n) for n in range(1, 9)]
    sheet = text.split("編號,", 1)[1].splitlines()
    assert sheet[0] == "第1類,第2類,第3類,第4類,第5類,第6類,第7類,你猜這篇是哪一組（P／M／不知道）"
    assert len(sheet) == 9 and all(line.count(",") == 8 for line in sheet[1:])
    assert "來源：\n- cna｜來源標題" in text and "｜來源摘要" in text


def test_mapping_fields_and_hash_can_be_recomputed(session):
    _edition(session, DAY, 9)
    _, mapping, digest = export_blind_count(session, [DAY])
    meta = mapping["1"]
    assert set(meta) == {"edition_date", "story_id", "variant", "version", "keeper_cluster_id",
                         "merged_cluster_ids", "section", "hold"}
    assert meta["merged_cluster_ids"] == [meta["keeper_cluster_id"] + 1000]
    blob = json.dumps(mapping, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    assert blob == mapping_bytes(mapping) and hashlib.sha256(blob).hexdigest() == digest


def test_spot_check_is_lead_plus_one_reproducible_pick(session):
    stories = _edition(session, DAY, 4, m_only=(9,))
    sheet = spot_check_sheet(session, DAY)
    assert sheet == spot_check_sheet(session, DAY)
    lead, picked = sheet.split("## 頭版主稿")[1].split("## 隨機一則")
    assert f"事件{stories[(MAS, 1)].keeper_cluster_id}標題" in lead
    assert "事件1標題" not in picked and "（沒有）" not in picked
    assert "｜來源標題" in picked and "｜來源摘要" in picked


@contextmanager
def _scope(session):
    yield session
    session.flush()


def test_export_annotation_writes_files_and_verifiable_hash(session, tmp_path, monkeypatch):
    monkeypatch.setattr(run_module, "session_scope", lambda: _scope(session))
    _edition(session, DAY, 10)
    out = run_module.export_annotation(DAY, tmp_path)
    assert out == tmp_path / "2026-11-09"
    assert sorted(p.name for p in out.iterdir()) == ["blind.txt", "mapping.sha256", "spot-check.txt"]
    assert not list(out.rglob("mapping.json")) and not (out / "_private").exists()
    private = tmp_path / "_private" / "2026-11-09" / "mapping.json"
    assert private == private_mapping_path(tmp_path, DAY)
    raw = private.read_bytes()
    digest = (out / "mapping.sha256").read_text().strip()
    assert hashlib.sha256(raw).hexdigest() == digest == mapping_digest(json.loads(raw))
    mapping = json.loads(raw)
    assert [m["variant"] for m in mapping.values()].count(PIPELINE) == 4
    labels = {n: {"class1": 1, "guess": "P" if m["variant"] == PIPELINE else "不知道"} for n, m in mapping.items()}
    result = analyze_blind(labels, mapping)
    assert result["main_per_10"] == {PIPELINE: 10.0, MAS: 10.0}
    assert result["guess"] == {"guessed": 4, "correct": 4, "unsure": 4, "accuracy": 1.0}


def test_export_annotation_with_no_common_events_writes_readme(session, tmp_path, monkeypatch):
    monkeypatch.setattr(run_module, "session_scope", lambda: _scope(session))
    _edition(session, DAY, 0, p_only=(1,), m_only=(2,))
    out = run_module.export_annotation(DAY, tmp_path)
    assert sorted(p.name for p in out.iterdir()) == ["README.txt", "spot-check.txt"]
    assert "0 個" in (out / "README.txt").read_text(encoding="utf-8")
    assert not (tmp_path / "_private").exists()


def test_reexport_replaces_private_mapping_and_report_line(session, tmp_path, monkeypatch):
    monkeypatch.setattr(run_module, "session_scope", lambda: _scope(session))
    _edition(session, DAY, 10)
    private = private_mapping_path(tmp_path, DAY)
    first = run_module.export_annotation_report(DAY, tmp_path)
    private.write_bytes(b"tampered")
    second = run_module.export_annotation_report(DAY, tmp_path)
    digest = (tmp_path / "2026-11-09" / "mapping.sha256").read_text().strip()
    assert first == second == f"2026-11-09 {digest} {tmp_path / '2026-11-09'} {private}"
    assert hashlib.sha256(private.read_bytes()).hexdigest() == digest


def _analyze(argv):
    import importlib.util
    from pathlib import Path

    spec = importlib.util.spec_from_file_location("analyze_blind_count", Path("scripts/analyze_blind_count.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.main(argv)


def _exported_with_labels(session, tmp_path, monkeypatch):
    monkeypatch.setattr(run_module, "session_scope", lambda: _scope(session))
    _edition(session, DAY, 10)
    run_module.export_annotation(DAY, tmp_path)
    mapping = json.loads(private_mapping_path(tmp_path, DAY).read_bytes())
    labels = tmp_path / "labels.json"
    labels.write_text(json.dumps({n: {"class1": 1} for n in mapping}), encoding="utf-8")
    return labels


def test_analyze_script_reads_new_path_by_date_and_mapping(session, tmp_path, monkeypatch, capsys):
    labels = _exported_with_labels(session, tmp_path, monkeypatch)
    assert _analyze(["--labels", str(labels), "--root", str(tmp_path), "--date", "2026-11-09"]) == 0
    by_date = json.loads(capsys.readouterr().out)
    assert by_date["main_per_10"] == {PIPELINE: 10.0, MAS: 10.0}
    assert _analyze(["--labels", str(labels), "--mapping", str(private_mapping_path(tmp_path, DAY))]) == 0
    assert json.loads(capsys.readouterr().out) == by_date


def test_analyze_script_rejects_legacy_path(session, tmp_path, monkeypatch):
    labels = _exported_with_labels(session, tmp_path, monkeypatch)
    legacy = tmp_path / "2026-11-09" / "_private" / "mapping.json"
    legacy.parent.mkdir()
    private_mapping_path(tmp_path, DAY).rename(legacy)
    for argv in (["--root", str(tmp_path), "--date", "2026-11-09"], ["--mapping", str(legacy)]):
        with pytest.raises(SystemExit, match="舊位置.*_private/2026-11-09/mapping.json.*盲化"):
            _analyze(["--labels", str(labels), *argv])


def test_analyze_script_fails_when_mapping_or_hash_missing_or_changed(session, tmp_path, monkeypatch):
    labels = _exported_with_labels(session, tmp_path, monkeypatch)
    argv = ["--labels", str(labels), "--root", str(tmp_path), "--date", "2026-11-09"]
    private = private_mapping_path(tmp_path, DAY)
    original = private.read_bytes()
    private.write_bytes(original.replace(b'"pipeline"', b'"mas"', 1))
    with pytest.raises(SystemExit, match="SHA-256"):
        _analyze(argv)
    private.write_bytes(original)
    (tmp_path / "2026-11-09" / "mapping.sha256").unlink()
    with pytest.raises(SystemExit, match="mapping.sha256"):
        _analyze(argv)
    private.unlink()
    with pytest.raises(SystemExit, match="找不到對照表"):
        _analyze(argv)


def test_analyze_hold_sensitivity_counts_hold_as_blocked():
    mapping = {
        "1": {"variant": PIPELINE, "hold": False},
        "2": {"variant": MAS, "hold": True},
        "3": {"variant": MAS, "hold": False},
    }
    labels = {"1": {"class1": 1}, "2": {"class2": 1, "class3": 1, "class6": 1}, "3": {"class5": 1, "class7": 1}}
    result = analyze_blind(labels, mapping)
    assert result["errors"][MAS] == [0, 1, 1, 0, 1, 1, 1]
    assert result["main_errors"] == {PIPELINE: 1, MAS: 3}
    assert result["main_per_10"] == {PIPELINE: 10.0, MAS: 15.0}
    assert result["hold_count"] == 1
    assert result["hold_blocked"]["main_errors"] == {PIPELINE: 1, MAS: 1}
    assert result["hold_blocked"]["main_per_10"][MAS] == 5.0

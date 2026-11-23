"""scripts/trial_metrics.py：重複主稿候選（事件層級）與唯讀開檔。"""

from __future__ import annotations

import importlib.util
import json
import sqlite3
from datetime import date
from pathlib import Path

import pytest

DAY = date(2026, 11, 14)


def _module():
    spec = importlib.util.spec_from_file_location("trial_metrics", Path("scripts/trial_metrics.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def tm():
    return _module()


def _db(path):
    conn = sqlite3.connect(path)
    conn.executescript("""
        CREATE TABLE stories (id INTEGER, edition_date TEXT, run_variant TEXT, keeper_cluster_id INTEGER, merged_cluster_ids TEXT);
        CREATE TABLE story_versions (story_id INTEGER, version INTEGER, headline TEXT, source_ids TEXT);
        CREATE TABLE daily_editions (id INTEGER, edition_date TEXT);
        CREATE TABLE daily_articles (edition_id INTEGER, cluster_id INTEGER);
        INSERT INTO daily_editions VALUES (1, '2026-11-14');
    """)
    return conn


def _story(conn, story_id, variant, keeper, headline, sources, *, merged=(), version=1, printed=True):
    if version == 1:
        conn.execute("INSERT INTO stories VALUES (?,?,?,?,?)", (story_id, DAY.isoformat(), variant, keeper, json.dumps(list(merged))))
        if variant == "mas" and printed:
            conn.execute("INSERT INTO daily_articles VALUES (1,?)", (keeper,))
    conn.execute("INSERT INTO story_versions VALUES (?,?,?,?)", (story_id, version, headline, json.dumps(sources)))


def test_candidates_are_per_event_not_per_wording(tm, tmp_path):
    # 同一對事件：P 的標題很像、M 改寫後不像，兩組都要算到同一對
    conn = _db(tmp_path / "a.db")
    _story(conn, 1, "pipeline", 10, "美參院要求黃仁勳12月3日作證", [1])
    _story(conn, 2, "pipeline", 20, "輝達風波延燒　美參院要求黃仁勳、盧特尼克作證", [2])
    _story(conn, 3, "mas", 10, "Nvidia hearing set", [1])
    _story(conn, 4, "mas", 20, "商務部長列席聽證", [2])
    (pair,) = tm.duplicate_candidates(conn, DAY)
    assert pair["clusters"] == (10, 20) and set(pair["stories"]) == {"pipeline", "mas"}
    assert not pair["same_cluster"] and not pair["shared_source"]


def test_shared_cluster_or_source_counts_even_if_titles_differ(tm, tmp_path):
    conn = _db(tmp_path / "a.db")
    _story(conn, 1, "pipeline", 10, "甲乙丙丁", [1], merged=[30])
    _story(conn, 2, "pipeline", 20, "子丑寅卯", [2], merged=[30])
    _story(conn, 3, "pipeline", 40, "東西南北", [2])
    pairs = {p["clusters"]: p for p in tm.duplicate_candidates(conn, DAY)}
    assert pairs[(10, 20)]["same_cluster"] and pairs[(20, 40)]["shared_source"] and (10, 40) not in pairs


def test_unprinted_mas_story_is_not_counted(tm, tmp_path):
    conn = _db(tmp_path / "a.db")
    _story(conn, 1, "mas", 10, "美參院要求黃仁勳作證", [1])
    _story(conn, 2, "mas", 20, "美參院要求黃仁勳作證", [2], printed=False)
    assert tm.duplicate_candidates(conn, DAY) == []


def test_uses_the_latest_version(tm, tmp_path):
    conn = _db(tmp_path / "a.db")
    _story(conn, 1, "mas", 10, "美參院要求黃仁勳作證", [1])
    _story(conn, 2, "mas", 20, "美參院要求黃仁勳作證", [2])
    _story(conn, 2, "mas", 20, "教宗抵達阿根廷", [2], version=2)
    assert tm.duplicate_candidates(conn, DAY) == []


def test_unrelated_english_headlines_do_not_match_on_letters(tm):
    assert tm.title_similarity("US Treasury Secretary Scott Bessent relocated after alleged Iranian threats",
                               "Workers across Spain stage first general strike in 14 years") < tm.DUP_TITLE_SIMILARITY


def test_open_ro_reads_a_wal_copy_without_side_files_and_refuses_writes(tm, tmp_path):
    path = tmp_path / "copy.db"
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("CREATE TABLE t (x)")
    conn.commit()
    conn.close()
    ro = tm.open_ro(str(path))
    assert ro.execute("SELECT count(*) FROM t").fetchone() == (0,)
    with pytest.raises(sqlite3.OperationalError):
        ro.execute("INSERT INTO t VALUES (1)")
    ro.close()
    assert [p.name for p in tmp_path.iterdir()] == ["copy.db"]

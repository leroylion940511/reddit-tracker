"""模型雜訊偵測（daily/noise.py）與離線掃描腳本 scripts/scan_model_noise.py。"""

from __future__ import annotations

import importlib.util
import json
import sqlite3
from pathlib import Path

from reddit_tracker.daily.noise import model_noise, story_noise

# 11/15 刊出的 M 組稿 69855 的 why_it_matters（實際雜訊，人名照登）
LEAK_69855 = (
    "台北市長選情牽動地方施政走向 [S1]内 wait stop wrong? final already text need close proper. } "
    "I'm generating need valid JSON exact."
)


def _module():
    spec = importlib.util.spec_from_file_location("scan_model_noise", Path("scripts/scan_model_noise.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_catches_69855_leak():
    hits = model_noise(LEAK_69855)
    assert any("wait stop wrong?" in h for h in hits)
    assert "}" in hits
    assert any(h.lower().startswith("i'm") for h in hits)


def test_catches_json_leftovers():
    assert model_noise('輝達財報優於預期 [S1]。","why_it_matters":"影響台灣供應鏈')
    assert model_noise('台積電擴產 {"action": "PASS"}')
    assert model_noise('正文結束\\"')


def test_chinese_news_with_english_names_is_clean():
    clean = [
        "OpenAI 執行長 Sam Altman 表示，ChatGPT 每週有 8 億用戶 [S1]。",
        "蘋果發表 iPhone 18，搭載 A20 晶片；Apple Intelligence 將支援繁體中文 [S2]。",
        "Meta 開源 Llama 5，採用 open source 授權，開發者可在 Hugging Face 下載 [S1]。",
        "美國聯準會 Fed 維持利率不變，市場預期 12 月降息 [S1][S2]。",
        "研究以 arXiv 預印本形式發表，尚未經同儕審查。",
        # 11/15 P 組模板稿 69845：直接貼英文摘要，不是模型雜訊
        "據The Guardian World報導：Filipino entry, pop and rap song Sobra-Sobra, takes 19-year-old "
        "to victory at grand final in Bangkok Carmelle Collado ha…",
        "",
        None,
    ]
    for text in clean:
        assert model_noise(text) == [], text


def test_story_noise_only_returns_hit_fields():
    result = story_noise({"headline": "台積電擴產", "body": "正常正文 [S1]。", "why_it_matters": LEAK_69855})
    assert list(result) == ["why_it_matters"]


def _db(path: Path) -> None:
    conn = sqlite3.connect(path)
    conn.executescript(
        "CREATE TABLE stories (id INTEGER PRIMARY KEY, edition_date DATE, run_variant TEXT);"
        "CREATE TABLE story_versions (id INTEGER PRIMARY KEY, story_id INTEGER, version INTEGER, run_variant TEXT,"
        " headline TEXT, deck TEXT, body TEXT, why_it_matters TEXT, status TEXT, approved_by TEXT);"
    )
    conn.executemany("INSERT INTO stories VALUES (?,?,?)",
                     [(1, "2026-11-15", "mas"), (2, "2026-11-15", "mas"), (3, "2026-11-16", "mas")])
    conn.executemany(
        "INSERT INTO story_versions (story_id, version, run_variant, headline, deck, body, why_it_matters, status,"
        " approved_by) VALUES (?,?,?,?,?,?,?,?,?)",
        [
            (1, 1, "mas", "標題", "導言", "正文 [S1]。", LEAK_69855, "checked", None),
            (2, 1, "mas", "標題", "導言", 'I need to fix this 正文 [S1]。', "重要", "draft", None),
            (2, 2, "mas", "標題", "導言", "正文 [S1]。", "重要", "checked", "editor"),
            (3, 1, "mas", "標題", "導言", "正文 [S1]。", LEAK_69855, "checked", None),  # 範圍外
        ],
    )
    conn.commit()
    conn.close()


def test_scan_db_is_read_only_and_marks_latest(tmp_path, capsys):
    db = tmp_path / "copy.db"
    _db(db)
    before = db.read_bytes()
    scan = _module()
    assert scan.main(["--db", str(db), "--start", "2026-11-15"]) == 0
    out = capsys.readouterr().out
    assert db.read_bytes() == before
    lines = [line for line in out.splitlines() if line.startswith("| 2026")]
    assert len(lines) == 2  # story 1 v1（最新版）＋ story 2 v1（中間版）；11/16 不在範圍
    assert "| 1 | 1 | 是 | checked | 否 | why_it_matters |" in lines[0]
    assert "| 2 | 1 | 否 | draft | 否 | body |" in lines[1]


def test_scan_json_and_clean_output(tmp_path, capsys):
    path = tmp_path / "v1.json"
    path.write_text(json.dumps({
        "E01": {"headline": "標題", "deck": "", "body": "正文 [S1]。", "why_it_matters": "重要"},
        "N03": {"headline": "標題", "deck": "", "body": "正文 [S1]。", "why_it_matters": LEAK_69855},
    }, ensure_ascii=False), encoding="utf-8")
    scan = _module()
    assert scan.main(["--json", str(path)]) == 0
    out = capsys.readouterr().out
    assert "N03" in out and "E01" not in out

    path.write_text(json.dumps({"E01": {"headline": "標題", "body": "正文"}}), encoding="utf-8")
    scan.main(["--json", str(path)])
    assert capsys.readouterr().out.strip() == "沒有發現模型雜訊。"

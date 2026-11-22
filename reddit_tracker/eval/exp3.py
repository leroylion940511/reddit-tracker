"""實驗三結果計算（手冊 8.3、9.4；步驟 12）：P（流水線）vs M（MAS）的盲計錯誤數。

只做算術，不碰 DB、不呼叫 LLM。輸入：
- 標註員 B 的原始輸出（B＝agy CLI，2026-11-17 志晨確認沒有人類標註員）：每期一個
  `B_raw_YYYY-MM-DD.json`，是 `agy -p … --output-format json --json-schema schema_count.json` 的整包輸出，
  `response` 欄位是符合 schema 的 JSON 字串。
- 每期的對照表 `annotation/_private/YYYY-MM-DD/mapping.json`（讀之前用 `mapping.sha256` 驗證；
  驗證與讀檔沿用 `scripts/analyze_blind_count.py::_load`）。

每期的錯誤數、主指標、HOLD 敏感度、猜組別都直接用 `daily/blind.py::analyze_blind`，這裡只負責
拆成每期、加總、符號檢定與產生報告。符號檢定是 exact 雙尾二項檢定（等同 `scipy.stats.binomtest(k, n, 0.5)`），
差為 0 的期數不計入 n。
"""

from __future__ import annotations

import json
import math
from datetime import date
from pathlib import Path

from reddit_tracker.daily.blind import ERROR_CLASSES, MAIN_CLASSES, analyze_blind
from reddit_tracker.daily.store import MAS, PIPELINE
from reddit_tracker.eval.exp2 import MANUAL_MARKER, keep_manual

CLASS_NAMES = ("無關來源", "標題與內文不一", "數字沒有出處", "矛盾沒標", "譯名不一", "分版錯", "假多來源")
LETTER = {PIPELINE: "P", MAS: "M"}

__all__ = ["MANUAL_MARKER", "keep_manual"]


class Exp3Error(ValueError):
    pass


# ── 讀 B 的輸出 ─────────────────────────────────────────────────────────────


def parse_agy(raw: str, expected: int) -> dict[str, dict]:
    """agy 的整包 JSON → {"編號": {"class1".."class7", "guess", "reason"}}；編號要剛好是 1..expected。"""
    envelope = json.loads(raw)
    if envelope.get("status") != "SUCCESS":
        raise Exp3Error(f"agy 沒有成功：status={envelope.get('status')!r}")
    body = envelope["response"]
    items = (json.loads(body) if isinstance(body, str) else body)["items"]
    labels: dict[str, dict] = {}
    for item in items:
        number = str(int(item["number"]))
        if number in labels:
            raise Exp3Error(f"編號 {number} 出現兩次")
        marks = {f"class{i}": int(item[f"class{i}"]) for i in range(1, ERROR_CLASSES + 1)}
        if any(value not in (0, 1) for value in marks.values()):
            raise Exp3Error(f"編號 {number} 的錯誤欄位不是 0／1：{marks}")
        labels[number] = {**marks, "guess": str(item.get("guess") or "不知道"), "reason": str(item.get("reason") or "")}
    want = {str(n) for n in range(1, expected + 1)}
    if set(labels) != want:
        raise Exp3Error(f"編號不齊：缺 {sorted(want - set(labels), key=int)}，多 {sorted(set(labels) - want, key=int)}")
    return labels


def count_items(blind_text: str) -> int:
    """blind.txt 的篇數（每篇以單獨一行 `#N` 開頭）。"""
    return sum(1 for line in blind_text.splitlines() if line.startswith("#") and line[1:].strip().isdigit())


# ── 計算 ──────────────────────────────────────────────────────────────────


def sign_test(diffs: list[float]) -> dict:
    """exact 雙尾符號檢定：M−P 的差 >0 與 <0 的期數，差為 0 不計。"""
    positive = sum(1 for d in diffs if d > 0)
    negative = sum(1 for d in diffs if d < 0)
    n = positive + negative
    if n == 0:
        return {"positive": 0, "negative": 0, "n": 0, "p_value": None}
    k = min(positive, negative)
    tail = sum(math.comb(n, i) for i in range(k + 1)) / 2**n
    return {"positive": positive, "negative": negative, "n": n, "p_value": round(min(1.0, 2 * tail), 4)}


def compute(labels_by_day: dict[str, dict], mappings: dict[str, dict]) -> dict:
    """labels_by_day／mappings：出刊日 → 該期的 labels／對照表。回傳每期結果、合計與符號檢定。"""
    days = sorted(mappings)
    missing = [d for d in days if d not in labels_by_day]
    if missing:
        raise Exp3Error(f"這幾期沒有 B 的結果：{missing}")
    per_day = {d: analyze_blind(labels_by_day[d], mappings[d]) for d in days}
    merged_labels = {f"{d}:{n}": mark for d in days for n, mark in labels_by_day[d].items()}
    merged_mapping = {f"{d}:{n}": meta for d in days for n, meta in mappings[d].items()}
    total = analyze_blind(merged_labels, merged_mapping)
    diffs = []
    for d in days:
        rate = per_day[d]["main_per_10"]
        if rate[PIPELINE] is not None and rate[MAS] is not None:
            diffs.append(rate[MAS] - rate[PIPELINE])
    return {"days": days, "per_day": per_day, "total": total, "sign": sign_test(diffs),
            "labels": merged_labels, "mapping": merged_mapping}


# ── 報告 ──────────────────────────────────────────────────────────────────


def _fmt(value: float | None) -> str:
    return "—" if value is None else f"{value:g}"


def _marked(mark: dict, upto: int = ERROR_CLASSES) -> list[int]:
    return [i for i in range(1, upto + 1) if int(mark.get(f"class{i}") or 0)]


def render_report(result: dict, generated_at: str, model_note: str) -> str:
    days, per_day, total, sign = result["days"], result["per_day"], result["total"], result["sign"]
    span = f"{days[0]}～{days[-1]}" if days else "—"
    lines = [
        "# 實驗三結果：P（流水線）vs M（MAS）盲計錯誤數",
        "",
        f"> 由 `scripts/exp3_results.py` 產生（{generated_at}）。期間 {span}，共 {len(days)} 期。"
        f"標註員 B＝{model_note}（AI 工具代標，不是人類標註員）。",
        "> 每期 8 篇、P／M 各 4 篇，抽自兩組都有寫的事件（`BLIND_SEED=20261201`）；對照表用事先 commit 的",
        "> `docs/eval/blind_mapping.sha256` 驗證後才讀。計錯點是 ⑦a 程式檢查之後、⑦b 人工核准之前的版本（手冊 8.3）。",
        "",
        "## 主指標（每 10 篇第 1–5 類錯誤數）",
        "",
        "| 出刊日 | P 篇數 | P 錯誤 | P 每 10 篇 | M 篇數 | M 錯誤 | M 每 10 篇 | M−P | M HOLD 篇數 |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for d in days:
        r = per_day[d]
        rate = r["main_per_10"]
        diff = None if rate[PIPELINE] is None or rate[MAS] is None else round(rate[MAS] - rate[PIPELINE], 2)
        lines.append(
            f"| {d} | {r['counts'][PIPELINE]} | {r['main_errors'][PIPELINE]} | {_fmt(rate[PIPELINE])} "
            f"| {r['counts'][MAS]} | {r['main_errors'][MAS]} | {_fmt(rate[MAS])} | {_fmt(diff)} | {r['hold_count']} |"
        )
    t = total
    lines += [
        f"| **合計** | {t['counts'][PIPELINE]} | {t['main_errors'][PIPELINE]} | {_fmt(t['main_per_10'][PIPELINE])} "
        f"| {t['counts'][MAS]} | {t['main_errors'][MAS]} | {_fmt(t['main_per_10'][MAS])} "
        f"| {_fmt(None if t['main_per_10'][PIPELINE] is None or t['main_per_10'][MAS] is None else round(t['main_per_10'][MAS] - t['main_per_10'][PIPELINE], 2))} "
        f"| {t['hold_count']} |",
        "",
        f"在這 {len(days)} 期中，M 每 10 篇有 {_fmt(t['main_per_10'][MAS])} 個第 1–5 類錯誤、"
        f"P 有 {_fmt(t['main_per_10'][PIPELINE])} 個。",
        "",
        f"- 符號檢定（輔助，exact 雙尾，差為 0 的期數不計）：M 較多 {sign['positive']} 期、P 較多 {sign['negative']} 期、"
        f"n={sign['n']}，p={_fmt(sign['p_value'])}。7 期太少，不能據此說哪一組比較好。",
        f"- HOLD 敏感度版本（M 被 HOLD 的稿算已擋下、錯誤記 0）：M 每 10 篇 {_fmt(t['hold_blocked']['main_per_10'][MAS])}、"
        f"P {_fmt(t['hold_blocked']['main_per_10'][PIPELINE])}；抽樣裡 M 的 HOLD 稿共 {t['hold_count']} 篇。",
        "- 排除降級日的版本：降級日要從各期 `daily_editions.stats` 確認（`scripts/trial_metrics.py`），見下方手寫分析。",
        "",
        "## 各類錯誤（含第 6、7 類）",
        "",
        "| 類別 | P | M |",
        "| --- | --- | --- |",
    ]
    for index, name in enumerate(CLASS_NAMES):
        tag = "" if index < MAIN_CLASSES else "（上游共用，不算主指標）"
        lines.append(f"| {index + 1}. {name}{tag} | {t['errors'][PIPELINE][index]} | {t['errors'][MAS][index]} |")
    g = t["guess"]
    lines += [
        "",
        "## 盲化檢查：B 猜組別",
        "",
        f"B 有猜的 {g['guessed']} 篇中猜對 {g['correct']} 篇（正確率 {_fmt(g['accuracy'])}），填「不知道」{g['unsure']} 篇。"
        + (" 明顯高於 50%，限制章節要寫「盲化可能失效」。" if g["accuracy"] is not None and g["accuracy"] >= 0.65 else
           " 沒有明顯高於 50%，看不出盲化失效。"),
        "",
        "## 逐篇明細（有標錯的稿）",
        "",
        "| 出刊日 | 編號 | 組 | 版 | story_id | 標的類別 | HOLD | B 的理由 |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for key in sorted(result["mapping"], key=lambda k: (k.split(":")[0], int(k.split(":")[1]))):
        meta, mark = result["mapping"][key], result["labels"].get(key, {})
        classes = _marked(mark)
        if not classes:
            continue
        day, number = key.split(":")
        reason = str(mark.get("reason", "")).replace("|", "／").replace("\n", " ")
        lines.append(
            f"| {day} | {number} | {LETTER.get(meta['variant'], meta['variant'])} | {meta.get('section', '')} "
            f"| {meta.get('story_id', '')} | {','.join(map(str, classes))} | {'是' if meta.get('hold') else ''} | {reason} |"
        )
    lines += [
        "",
        "## 怎麼重產",
        "",
        "```bash",
        "uv run python scripts/exp3_results.py --start 2026-11-09 --end 2026-11-15 --write",
        "```",
        "",
        "只讀 `docs/eval/exp3/B_labels.json`（B 的原始輸出解析後存檔）與 `annotation/_private/` 的對照表；不碰 DB、不呼叫 LLM。",
        "",
    ]
    return "\n".join(lines)


def load_raw_labels(raw_dir: Path, blind_root: Path, day: date) -> dict[str, dict]:
    """讀 raw_dir/B_raw_YYYY-MM-DD.json，篇數以 blind_root/YYYY-MM-DD/blind.txt 或 raw_dir/blind_YYYY-MM-DD.txt 為準。"""
    d = day.isoformat()
    blind = blind_root / d / "blind.txt"
    if not blind.is_file():
        blind = raw_dir / f"blind_{d}.txt"
    expected = count_items(blind.read_text(encoding="utf-8"))
    return parse_agy((raw_dir / f"B_raw_{d}.json").read_text(encoding="utf-8"), expected)

"""回歸案例的條件：每個條件是一個函式 `(case, view) -> 違規清單`，空清單代表通過。

同一套條件跑兩種版面（見 rebuild.py）：
- 刊出版（10/27 實際）：每個錯誤案例的每個條件都必須抓到違規，證明條件有效。
- 重編版：修好之後必須沒有違規。

條件分兩類：
- 事件／版面層（不需要 LLM 文字）：證據包、合併、分版、轉載、選題、數據欄。
- 文字層（`TEXT_CONDITIONS`）：需要撰稿結果。重編版要有錄好的回應（request_hash replay），
  找不到就直接失敗；事件在重編版沒見報時這個條件不適用（skip）。
"""

from __future__ import annotations

import re
from datetime import date, timedelta

import pytest

from .rebuild import EditionView, Story, norm_title

ARXIV_PREFIX = "arxiv"


class NotApplicable(Exception):
    """這個版面上沒有可檢查的對象（例如事件沒見報）。"""


def _events(case: dict, view: EditionView) -> list[Story]:
    events = view.events_with(case["event_titles"])
    if not events:
        pytest.fail(f"{case['case_id']}：{view.name} 版面找不到事件（event_titles 都不在任何事件裡）")
    return events


def _published_events(case: dict, view: EditionView) -> list[Story]:
    events = [s for s in view.events_with(case["event_titles"]) if s.published]
    if not events:
        raise NotApplicable(f"{case['case_id']} 的事件在 {view.name} 版面沒見報")
    return events


def _arxiv_only(story: Story) -> bool:
    return bool(story.sources) and all(s["source_id"].startswith(ARXIV_PREFIX) for s in story.sources)


# ── 事件／版面層 ──────────────────────────────────────────────────────────


def must_not_contain_titles(case: dict, view: EditionView) -> list[str]:
    banned = {norm_title(t): t for t in case["must_not_contain_titles"]}
    return [
        f"{story.key} 的來源含不相干素材：{banned[title]}"
        for story in _events(case, view)
        for title in story.source_titles
        if title in banned
    ]


def must_merge_titles(case: dict, view: EditionView) -> list[str]:
    """整組標題要在同一則；而且同一事件（整組＋`same_event_titles`）最多只見報一次。"""
    same_event = {norm_title(t) for t in case.get("same_event_titles", [])}
    problems = []
    for group in case["must_merge_titles"]:
        wanted = {norm_title(t) for t in group}
        if not any(wanted <= story.members for story in view.events):
            problems.append(f"沒有任何一則包含整組同一事件：{group}")
        published = [s.key for s in view.published if s.members & (wanted | same_event)]
        if len(published) > 1:
            problems.append(f"同一事件見報 {len(published)} 次：{published}")
    return problems


def expected_section(case: dict, view: EditionView) -> list[str]:
    events = _events(case, view)
    published = [s for s in events if s.published] or events
    want = case["expected_section"]
    return [f"{s.key} 在 {s.section} 版，應在 {want} 版" for s in published if s.section != want]


def reprint_pairs(case: dict, view: EditionView) -> list[str]:
    """轉載只算 1 個來源：兩篇要在同一事件、出處不得並列兩次、事件的家數不得把它算 2 家。"""
    problems = []
    for original, reprint in case["reprint_pairs"]:
        a, b = norm_title(original), norm_title(reprint)
        events = [s for s in view.events if a in s.members and b in s.members]
        if not events:
            problems.append(f"轉載沒有歸入同一事件：{reprint}")
            continue
        for story in events:
            titles = story.source_titles
            if a in titles and b in titles:
                problems.append(f"{story.key} 把轉載當兩個來源並列：{original}／{reprint}")
            for cluster in story.clusters:
                members = {m["title"]: m for m in cluster.members}
                if a not in members or b not in members:
                    continue
                outlets = {
                    members[a]["outlet"] if m["title"] == b else m["outlet"]
                    for m in cluster.members
                    if m["tier"] != "T4"
                }
                if cluster.outlet_count > len(outlets):
                    problems.append(
                        f"cluster {cluster.cluster_id} 算 {cluster.outlet_count} 家，轉載合併後只有 {len(outlets)} 家"
                    )
    return problems


def must_not_publish_titles(case: dict, view: EditionView) -> list[str]:
    banned = {norm_title(t): t for t in case["must_not_publish_titles"]}
    return [
        f"{story.key} 刊出了不該刊的素材：{banned[title]}"
        for story in view.published
        for title in story.source_titles
        if title in banned
    ]


def _previous_trading_day(day: date) -> date:
    day -= timedelta(days=1)
    while day.weekday() >= 5:
        day -= timedelta(days=1)
    return day


def market_stale_label(case: dict, view: EditionView) -> list[str]:
    if not view.market:
        raise NotApplicable("數據欄沒有資料")
    closes = {date.fromisoformat(m["date"]) for m in view.market if m.get("date")}
    latest_expected = _previous_trading_day(view.edition_date)
    if not closes or min(closes) >= latest_expected:
        return []  # 不落後就不需要標示
    label = case["market_stale_label"]
    if label not in view.html:
        return [f"數據欄收盤日 {min(closes)} 早於 {latest_expected}，版面沒有「{label}」"]
    return []


# ── 文字層 ────────────────────────────────────────────────────────────────


def text_must_not_contain(case: dict, view: EditionView) -> list[str]:
    stories = _published_events(case, view)
    require_written(view)
    return [
        f"{s.key} 稿件提到不相干內容「{word}」"
        for s in stories
        for word in case["text_must_not_contain"]
        if word in s.text
    ]


def headline_must_not_match(case: dict, view: EditionView) -> list[str]:
    stories = _published_events(case, view)
    require_written(view)
    return [
        f"{s.key} 標題「{s.headline}」符合禁止樣式 {pattern}"
        for s in stories
        for pattern in case["headline_must_not_match"]
        if re.search(pattern, s.headline or "")
    ]


def name_glossary(case: dict, view: EditionView) -> list[str]:
    if not view.published:
        raise NotApplicable("沒有刊出稿")
    require_written(view)
    problems = []
    for entry in case["name_glossary"]:
        used = [v for v in entry["variants"] if any(v in s.text for s in view.published)]
        if used:
            problems.append(f"同一份報紙出現非標準譯名 {used}，應統一為「{entry['preferred']}」")
    return problems


def arxiv_rules(case: dict, view: EditionView) -> list[str]:
    stories = [s for s in view.published if _arxiv_only(s)]
    if not stories:
        raise NotApplicable("沒有只來自 arXiv 的刊出稿")
    require_written(view)
    rules = case["arxiv_rules"]
    problems = []
    for s in stories:
        for pattern in rules["must_not_match"]:
            if re.search(pattern, s.text):
                problems.append(f"{s.key} arXiv 稿符合禁止樣式 {pattern}")
        if rules["body_must_contain"] not in (s.body or ""):
            problems.append(f"{s.key} arXiv 稿沒寫「{rules['body_must_contain']}」")
    return problems


def single_source_notice(case: dict, view: EditionView) -> list[str]:
    """單一來源警語只能是 single_source 稿正文的最後一段；其他地方都不能出現。"""
    if not view.published:
        raise NotApplicable("沒有刊出稿")
    require_written(view)
    rule = case["single_source_notice"]
    pattern = re.compile(rule["pattern"])
    problems = []
    for s in view.published:
        if rule.get("exempt_arxiv_only") and _arxiv_only(s):
            continue
        paragraphs = [p for p in (s.body or "").split("\n") if p.strip()]
        is_single = s.kind == "single_source"
        body_head = paragraphs[:-1] if is_single else paragraphs
        for where, text in [("標題", s.headline), ("導言", s.deck), ("重要性", s.why_it_matters)] + [
            ("正文", p) for p in body_head
        ]:
            if text and pattern.search(text):
                problems.append(f"{s.key}（{s.kind}）{where}夾帶單一來源警語：{text[:40]}")
        if is_single and not (paragraphs and pattern.search(paragraphs[-1])):
            problems.append(f"{s.key} 單一來源稿文末沒有警語")
    return problems


def require_written(view: EditionView) -> None:
    """重編版的文字必須來自錄好的回應；有任何 request_hash 找不到就失敗（不改呼叫真模型）。"""
    if view.replay_misses:
        unique = list(dict.fromkeys(view.replay_misses))
        pytest.fail(
            f"找不到錄好的 LLM 回應（{len(unique)} 個 request_hash，例如 {unique[0]}）；"
            "提示詞或證據包改了就要重錄：uv run python scripts/record_regression_1027.py（在 data/work 複本呼叫真 Codex）"
        )


EVENT_CONDITIONS = {
    "must_not_contain_titles": must_not_contain_titles,
    "must_merge_titles": must_merge_titles,
    "expected_section": expected_section,
    "reprint_pairs": reprint_pairs,
    "must_not_publish_titles": must_not_publish_titles,
    "market_stale_label": market_stale_label,
}
TEXT_CONDITIONS = {
    "text_must_not_contain": text_must_not_contain,
    "headline_must_not_match": headline_must_not_match,
    "name_glossary": name_glossary,
    "arxiv_rules": arxiv_rules,
    "single_source_notice": single_source_notice,
}
CONDITIONS = {**EVENT_CONDITIONS, **TEXT_CONDITIONS}
# 需要 event_titles 才能定位事件的條件
NEEDS_EVENT = {
    "must_not_contain_titles", "expected_section", "text_must_not_contain", "headline_must_not_match",
}


def referenced_titles(case: dict) -> list[str]:
    titles = list(case.get("event_titles", []))
    titles += case.get("must_not_contain_titles", [])
    titles += case.get("must_not_publish_titles", [])
    titles += [t for group in case.get("must_merge_titles", []) for t in group]
    titles += case.get("same_event_titles", [])
    titles += [t for pair in case.get("reprint_pairs", []) for t in pair]
    titles += case.get("non_contradiction", {}).get("titles", [])
    return titles


def run_condition(key: str, case: dict, view: EditionView) -> list[str]:
    try:
        return CONDITIONS[key](case, view)
    except NotApplicable as exc:
        pytest.skip(f"{case['case_id']} {key} 不適用：{exc}")

"""模型雜訊偵測：稿件欄位裡混進的模型推理文字或 JSON 殘渣。

起因：11/15 刊出的 M 組稿 69855 `why_it_matters` 在 `[S1]` 後面夾著
「wait stop wrong? final already text need close proper. } … I'm generating need valid JSON exact.」，
Codex 回傳的 JSON 欄位混進推理文字，現行流程沒有擋。

這裡只提供純函式，**線上流程還沒接**（11/20 凍結前不改線上行為）；目前只給
`scripts/scan_model_noise.py` 離線掃描已存的稿，報告用。凍結後要接成輸出檢查（重試或 HOLD）時沿用同一套規則。

規則故意保守（寧可漏報，不要把正常中文稿裡的英文專有名詞當雜訊）：
1. JSON 殘渣：稿件欄位名稱接冒號（`"body":`）、`{"`／`"}`／`\"`、單獨的 `}`／`{`。
2. 英文第一人稱：`I'm`、`I'll`、`I need`、`let me`。
3. 小寫英文連續 3 個字以上，而且其中有 2 個以上不同的推理用語（wait、final、need、json…）。專有名詞多半大寫開頭，
   不會算進去；只有一個用語的不算（P 組模板稿直接貼英文摘要，如 11/15 69845 的 “grand final”）。
"""

from __future__ import annotations

import re

FIELD_NAMES = ("headline", "deck", "body", "why_it_matters", "action", "reason", "source_ids")

_FIELD_KEY = re.compile(r'"?\b(?:' + "|".join(FIELD_NAMES) + r')"\s*:')
_JSON_EDGE = re.compile(r'\{\s*"|"\s*\}|\\"')
_LONE_BRACE = re.compile(r"(?:^|[\s。，；.,;!?？！])[{}](?=$|[\s。，；.,;!?？！])")
_FIRST_PERSON = re.compile(r"\bI['’](?:m|ll|ve|d)\b|\bI (?:need|will|should|must|think)\b|\blet me\b", re.IGNORECASE)
# 小寫英文字（可帶 ? ! . , 這類標點），連續 3 個以上
_LOWER_RUN = re.compile(r"(?<![A-Za-z'’])(?:[a-z][a-z'’]*[?!.,]?\s+){2,}[a-z][a-z'’]*[?!.,]?")
META_WORDS = frozenset({
    "wait", "stop", "wrong", "final", "already", "need", "needs", "output", "answer", "json", "schema",
    "generating", "generate", "proper", "close", "oops", "hmm", "actually", "exact", "valid", "field",
    "fields", "string", "respond", "response", "rewrite", "fix", "retry", "format",
})


def _words(run: str) -> list[str]:
    return [w.strip("?!.,'’").lower() for w in run.split()]


def model_noise(text: str | None) -> list[str]:
    """回傳命中的片段（原文，去重、照出現順序）；空 list 代表沒發現雜訊。"""
    if not text:
        return []
    hits: list[str] = []
    for pattern in (_FIELD_KEY, _JSON_EDGE, _FIRST_PERSON):
        hits.extend(m.group(0).strip() for m in pattern.finditer(text))
    hits.extend(m.group(0).strip(" 。，；.,;!?？！") for m in _LONE_BRACE.finditer(text))
    for m in _LOWER_RUN.finditer(text):
        if len(META_WORDS.intersection(_words(m.group(0)))) >= 2:
            hits.append(m.group(0).strip())
    return list(dict.fromkeys(h for h in hits if h))


def story_noise(fields: dict[str, str | None]) -> dict[str, list[str]]:
    """對多個欄位跑 `model_noise`；只回有命中的欄位。"""
    return {name: hits for name, value in fields.items() if (hits := model_noise(value))}

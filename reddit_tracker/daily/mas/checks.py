"""M 組的純判斷：注入標記、查核員的程式點名與逐來源判斷、頭版決定的格式檢查（P3-3 拆分）。

只放不碰 DB、不呼叫模型的函式與資料型別；`orchestrator.py` 以同名重新匯出，舊名稱相容。
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, replace

from pydantic import BaseModel, Field, ValidationError

from ...collection.entities import EntityContext, load_lexicon, rare_shared_fragments
from ..evidence import EvidenceItem
from .prompts import EVENT_RELATION_KEEP

logger = logging.getLogger(__name__)

FRONT_CAPACITY = 6

# FACT_CHECKER_ZH_FRAGMENTS：程式點名時，至少要和 S1 共有幾段互不相連的當天少見中文片段才不點名
CHECKER_MIN_ZH_FRAGMENTS = 2

INJECTION_MARKERS = (
    "忽略以上規則", "忽略以上指示", "ignore previous", "ignore the above", "把這篇放頭版",
)


class _Draft(BaseModel):
    action: str
    headline: str = ""
    deck: str = ""
    body: str = ""
    why_it_matters: str = ""
    reason: str = ""


class _Checker(BaseModel):
    action: str
    problem: str = "NONE"
    detail: str = ""
    required_action: str = ""
    sources: list[dict] = Field(default_factory=list)


class _Decision(BaseModel):
    lead: int | None = None
    second: list[int] = Field(default_factory=list)
    briefs: list[int] = Field(default_factory=list)
    links: list[dict] = Field(default_factory=list)
    dropped: list[dict] = Field(default_factory=list)
    reasons: list[dict] = Field(default_factory=list)


@dataclass
class Pitch:
    section: str
    story_id: int
    angle: str
    priority: str = "section"  # front | section
    sender: str = "section_editor"


def _has_marker(text: str) -> bool:
    text = text.lower()
    return any(marker.lower() in text for marker in INJECTION_MARKERS)


def evidence_has_injection(evidence: list[EvidenceItem]) -> bool:
    text = " ".join(f"{item.title}\n{item.summary}" for item in evidence).lower()
    if any(marker.lower() in text for marker in INJECTION_MARKERS):
        return True
    # desk-v3 D3：全文也要掃（只有 MAS_REPORTER_FULLTEXT 開啟時才會有 fulltext）
    return any(_has_marker(getattr(item, "fulltext", None) or "") for item in evidence)


def _usable_fulltext(item: EvidenceItem) -> str | None:
    """可以放進提示的全文；沒有或含注入標記時回 None（該篇退回摘要）。"""
    text = getattr(item, "fulltext", None)
    if not text or _has_marker(text):
        return None
    return text


def _evidence_text(evidence: list[EvidenceItem]) -> str:
    """數字檢查用的證據文字；沒有全文時與舊寫法逐字相同。"""
    parts = []
    for item in evidence:
        full = _usable_fulltext(item)
        parts.append(f"{item.title} {item.summary}" + (f" {full}" if full else ""))
    return " ".join(parts)


def guard_pitches(pitches: list[Pitch], evidence_of: dict[int, list[EvidenceItem]], log: list[str]) -> list[Pitch]:
    """摘要裡的「放頭版」指令不能讓稿件上頭版。改成內版，並記入 log。"""
    safe = []
    for pitch in pitches:
        if pitch.priority == "front" and evidence_has_injection(evidence_of.get(pitch.story_id, [])):
            log.append(f"story {pitch.story_id}：來源內容含指示，不上頭版")
            logger.warning("prompt injection blocked from front page: story %s", pitch.story_id)
            safe.append(replace(pitch, priority="section"))
        else:
            safe.append(pitch)
    return safe


def _parse(text: str | None, model: type[BaseModel]):
    if not text:
        return None
    try:
        data = json.loads(text)
        if isinstance(data, list):
            return None
        return model.model_validate(data)
    except (json.JSONDecodeError, ValidationError, ValueError):
        return None


def irrelevant_sources(
    evidence: list[EvidenceItem], day_context: EntityContext | None = None,
) -> list[tuple[int, EvidenceItem]]:
    """跟代表標題（S1）沒有共同名字的來源（只看標題）。查核員的程式工具，不花 LLM。

    名字＝譯名表、句中大寫的英文字、3 位數以上數字；句首大寫字要同一證據包其他標題在句中
    也把它大寫才算（與聚合同一規則，例如「Binance hack: …」的 Binance）。
    `day_context`（當天素材的 EntityContext，`FACT_CHECKER_ZH_FRAGMENTS` 打開才傳）：另外承認與 S1
    共有、當天少見（`EntityContext.is_rare`，篇數 < 5%）的中文片段，但要 **至少兩段互不相連**
    （`CHECKER_MIN_ZH_FRAGMENTS`）：一段可能只是題材用語（11/01 高雄、台北辯論共有「市長選戰」，
    當天才 41 篇，比候選人名還少見），兩段（「李四川」「蘇巧慧」）才算同一事件的佐證。
    沒傳就不比中文片段：只拿證據包幾篇算篇數比例沒有意義。
    這裡挑出來的只是「可疑」，刪不刪由 `_check_and_maybe_revise` 依查核員判斷決定。
    """
    if len(evidence) < 2:
        return []
    lexicon = load_lexicon()
    entities = [lexicon.entities(item.title, (item.lang or "").startswith("zh")) for item in evidence]
    context = EntityContext(entities)
    anchor = context.names(entities[0])
    bad = []
    for index, (item, ent) in enumerate(zip(evidence[1:], entities[1:]), start=2):
        if anchor & context.names(ent):
            continue
        if day_context is not None and (
            len(rare_shared_fragments(entities[0], ent, day_context)) >= CHECKER_MIN_ZH_FRAGMENTS
        ):
            continue
        bad.append((index, item))
    return bad


def checker_says_same_event(assessment: str | None) -> bool:
    """查核員 LLM 回 action=OK：提示詞要它「無關來源必須提出異議」，OK 就是判定每個來源都和 S1 同一事件。

    CHALLENGE、沒有回應或格式錯都不算（照程式結果刪來源）。
    """
    parsed = _parse(assessment, _Checker)
    return parsed is not None and parsed.action.strip().upper() == "OK"


def _sid(value) -> int | None:
    text = str(value).strip().upper().removeprefix("S")
    return int(text) if text.isdigit() else None


def checker_source_verdicts(assessment: str | None, flagged: list[int]) -> dict[int, bool]:
    """查核員對每個程式點名來源的判斷：{sid: True＝保留}。

    有逐來源判斷（`sources`）的照它：`verdict` KEEP／REMOVE，或事件四分類的 `relation`
    （`EVENT_RELATION_KEEP`：同次事件、後續進展保留；無關、彙整稿刪）。沒提到的點名來源、或舊格式只有全域 action 的回應，
    照 `checker_says_same_event`（OK 保留、其他刪）。沒點名的來源 LLM 說 REMOVE 也不算：
    刪來源仍要程式先點名。沒有回應或格式錯＝全刪（照程式結果）。
    """
    parsed = _parse(assessment, _Checker)
    default = parsed is not None and parsed.action.strip().upper() == "OK"
    verdicts = {}
    for entry in (parsed.sources if parsed is not None else []):
        if not isinstance(entry, dict):
            continue
        sid, verdict = _sid(entry.get("sid")), str(entry.get("verdict", "")).strip().upper()
        relation = str(entry.get("relation", "")).strip().upper()
        if sid in flagged and verdict in ("KEEP", "REMOVE"):
            verdicts[sid] = verdict == "KEEP"
        elif sid in flagged and relation in EVENT_RELATION_KEEP:
            verdicts[sid] = EVENT_RELATION_KEEP[relation]
    return {sid: verdicts.get(sid, default) for sid in flagged}


def _percent_values(evidence: list[EvidenceItem], body: str) -> set[float]:
    import re
    found = set()
    for match in re.finditer(r"(\d+(?:\.\d+)?)\s*[%％]", body):
        found.add(float(match.group(1)))
    return found


def _decision_problems(decision: _Decision, hold_ids: set[int], min_front: int = 1) -> list[str]:
    problems = []
    full = [i for i in [decision.lead, *decision.second, *decision.briefs] if i is not None]
    if decision.lead is None:
        problems.append("頭版沒有主稿")
    if len(full) < min_front:
        problems.append(f"頭版要排滿 {min_front} 則（合格提案數與容量取小），只排了 {len(full)} 則")
    if len(full) != len(set(full)):
        problems.append("同一篇稿出現在頭版一個以上的位置")
    if decision.lead in hold_ids:
        problems.append("HOLD 的稿不能上頭版")
    if any(item in hold_ids for item in decision.second + decision.briefs):
        problems.append("HOLD 的稿不能上頭版")
    if len(full) > FRONT_CAPACITY:
        problems.append(f"頭版最多 {FRONT_CAPACITY} 個位置")
    return problems

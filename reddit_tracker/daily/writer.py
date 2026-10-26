"""日報撰稿：Gemini 每版一次請求；失敗或未過審稿關卡的稿件改用模板稿。

LLM 只負責文字。順序、板塊、報導類型、來源與所有評分數字都由程式決定。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Protocol

from pydantic import BaseModel, Field, ValidationError

from ..config import get_settings
from ..llm.gemini import GeminiClient, GeminiResult
from .evidence import EvidenceItem

HEADLINE_RANGE = (4, 60)
BODY_RANGE = (60, 900)
TEMPLATE_SUMMARY_CHARS = 120
KIND_LABELS = {"report": "", "single_source": "單一來源", "social": "社群觀察"}

SYSTEM_PROMPT = """你是台灣綜合日報的資深編輯，替繁體中文讀者撰寫新聞。
規則：
1. 只能使用提供的證據（各家媒體的標題與摘要），不可補充證據以外的事實、數字、引述、人名或背景。
2. 以「據某某報導」「某某指出」歸因；多家說法不一致時並陳，不自行裁決。
3. 英文與簡體素材轉為台灣慣用的繁體中文用語；外國人名可附原文。
4. kind 為 single_source 時，正文要明說目前只有一家媒體報導；kind 為 social 時，要明說這是網路社群討論，不代表整體民意，也不是已證實的事實。
5. 語氣中立、克制，不煽動、不下結論。
6. 輸出純 JSON，不要 Markdown。"""

_NUMBER = re.compile(r"\d+(?:[.,]\d+)*")


class _CompletionClient(Protocol):
    def complete(
        self, *, system: str, messages: list[dict], max_output_tokens: int, temperature: float,
        json_mode: bool = False,
    ) -> GeminiResult: ...


@dataclass
class WrittenStory:
    headline: str
    deck: str
    body: str
    why_it_matters: str
    writer: str
    review_notes: list[str] = field(default_factory=list)


class _Generated(BaseModel):
    id: int
    headline: str = Field(min_length=1)
    deck: str = ""
    body: str = Field(min_length=1)
    why_it_matters: str = ""


class _GeneratedBatch(BaseModel):
    stories: list[_Generated]


class _SameEventGroups(BaseModel):
    groups: list[list[int]]


DESK_SYSTEM_PROMPT = """你是新聞編輯會議的主持人。給你一批候選新聞的標題（中英文混合），
找出「報導同一件具體事件」的標題組，例如同一場選舉結果的中文與英文報導。
只是同一主題但不同事件（例如同一場選戰中的兩個不同活動）不算同一事件。輸出純 JSON。"""


def _wrap_list(content: str, key: str) -> dict:
    """Gemini 偶爾省略外層物件、直接回傳陣列；兩種形狀都接受。"""
    data = json.loads(content)
    return {key: data} if isinstance(data, list) else data


def _short_outlet(name: str) -> str:
    head = name.split(" ")[0]
    return head if re.search(r"[一-鿿]", head) else name


def template_story(evidence: list[EvidenceItem], kind: str) -> WrittenStory:
    # 中文報紙的模板稿優先用中文來源當主稿，避免頭版出現英文標題。
    lead = next((e for e in evidence if (e.lang or "").startswith("zh")), evidence[0])
    others = [e.source_name for e in evidence if e is not lead]
    summary = lead.summary[:TEMPLATE_SUMMARY_CHARS] + ("…" if len(lead.summary) > TEMPLATE_SUMMARY_CHARS else "")
    label = KIND_LABELS[kind]
    body = f"據{_short_outlet(lead.source_name)}報導：{summary or lead.title}"
    if others:
        body += f"\n\n另有{'、'.join(others)}報導此事。"
    if kind == "social":
        body += "\n\n此為網路社群討論，不代表整體民意，內容亦未經證實。"
    elif kind == "single_source":
        body += "\n\n目前僅有單一媒體報導，後續發展待確認。"
    return WrittenStory(
        headline=lead.title,
        deck=f"【{label}】" if label else "",
        body=body,
        why_it_matters="",
        writer="template",
    )


def _numbers(text: str) -> set[float]:
    values = set()
    for raw in _NUMBER.findall(text.replace(",", "")):
        try:
            values.add(float(raw))
        except ValueError:
            continue
    return values


def _number_supported(value: float, evidence_numbers: set[float]) -> bool:
    if value in evidence_numbers:
        return True
    for known in evidence_numbers:
        if known == 0:
            continue
        ratio = value / known
        for power in range(-4, 5):
            if abs(ratio - 10**power) < 1e-6 * 10**power:
                return True
    return False


def review_story(story: WrittenStory, evidence: list[EvidenceItem]) -> list[str]:
    """回傳未通過的原因；空 list 代表通過。"""
    problems = []
    if not HEADLINE_RANGE[0] <= len(story.headline) <= HEADLINE_RANGE[1]:
        problems.append(f"標題長度 {len(story.headline)} 不在範圍內")
    if not BODY_RANGE[0] <= len(story.body) <= BODY_RANGE[1]:
        problems.append(f"正文長度 {len(story.body)} 不在範圍內")
    evidence_numbers = _numbers(" ".join(f"{e.title} {e.summary} {e.published_at}" for e in evidence))
    written = " ".join((story.headline, story.deck, story.body, story.why_it_matters))
    unsupported = sorted(
        {
            raw
            for raw in _NUMBER.findall(written.replace(",", ""))
            if (len(raw.replace(".", "")) >= 2 or "." in raw)
            and not _number_supported(float(raw), evidence_numbers)
        }
    )
    if unsupported:
        problems.append(f"證據中找不到的數字：{', '.join(unsupported[:5])}")
    return problems


class GeminiDailyWriter:
    """一次請求寫完一個板塊的所有稿件。"""

    def __init__(self, *, client: _CompletionClient | None = None) -> None:
        settings = get_settings()
        self.client = client or GeminiClient(
            purpose="daily",
            model=settings.gemini_daily_model,
            daily_limit=settings.gemini_daily_limit,
        )
        self.requests = 0

    def find_same_events(self, candidates: list[tuple[int, str]]) -> list[list[int]]:
        """回傳報導同一事件的 id 組；只回傳 2 個以上的組，未知 id 會被丟棄。"""
        prompt = (
            '回傳 {"groups":[[id,id],...]}，沒有就回傳 {"groups":[]}。\n\n'
            + json.dumps([{"id": i, "title": title} for i, title in candidates], ensure_ascii=False)
        )
        self.requests += 1
        result = self.client.complete(
            system=DESK_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
            max_output_tokens=2_000,
            temperature=0.0,
            json_mode=True,
        )
        known = {i for i, _ in candidates}
        groups = _SameEventGroups.model_validate(_wrap_list(result.content, "groups")).groups
        return [[i for i in group if i in known] for group in groups if len({i for i in group if i in known}) >= 2]

    def write(self, section_label: str, stories: list[tuple[int, str, list[EvidenceItem]]]) -> dict[int, WrittenStory]:
        payload = [
            {
                "id": story_id,
                "kind": kind,
                "evidence": [
                    {"outlet": e.source_name, "title": e.title, "summary": e.summary, "published_at": e.published_at}
                    for e in evidence
                ],
            }
            for story_id, kind, evidence in stories
        ]
        prompt = (
            f"板塊：{section_label}。替每個 id 各寫一則新聞，回傳 "
            '{"stories":[{"id":1,"headline":"不超過 40 字","deck":"一句話重點",'
            '"body":"150 到 400 字正文，可分段","why_it_matters":"一句話說明對台灣讀者的意義"}]}。\n\n'
            + json.dumps({"stories": payload}, ensure_ascii=False, separators=(",", ":"))
        )
        self.requests += 1
        result = self.client.complete(
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
            max_output_tokens=8_000,
            temperature=0.3,
            json_mode=True,
        )
        try:
            batch = _GeneratedBatch.model_validate(_wrap_list(result.content, "stories"))
        except (ValidationError, ValueError) as exc:
            raise ValueError(f"Gemini JSON 驗證失敗：{exc}") from exc
        expected = {story_id for story_id, _, _ in stories}
        return {
            item.id: WrittenStory(
                headline=item.headline.strip(),
                deck=item.deck.strip(),
                body=item.body.strip(),
                why_it_matters=item.why_it_matters.strip(),
                writer="gemini",
            )
            for item in batch.stories
            if item.id in expected
        }

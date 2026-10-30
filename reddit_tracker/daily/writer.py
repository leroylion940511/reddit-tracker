"""日報撰稿：LLM（預設 Codex，可切 Gemini；離線開發用 fake）每版一次請求；失敗或未過審稿關卡的稿件改用模板稿。

LLM 只負責文字。順序、板塊、報導類型、來源與所有評分數字都由程式決定。
警語也由程式加（手冊 6.6、E16）：`finalize_story` 在單一來源、社群、預印本稿的正文最後
加一段固定警語；LLM 自己在稿件裡寫警語算未過審稿。只來自 arXiv 的稿件依 E12 規則：
寫成「一篇發表於 arXiv 的預印本論文指出」，不得寫「獨家」「一家媒體」。
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field
from typing import Protocol

from pydantic import BaseModel, Field, ValidationError

from ..collection.entities import EntityLexicon, load_lexicon
from ..config import get_settings
from .evidence import EvidenceItem, short_outlet

HEADLINE_RANGE = (4, 60)
BODY_RANGE = (60, 900)
TEMPLATE_SUMMARY_CHARS = 120
KIND_LABELS = {"report": "", "single_source": "單一來源", "social": "社群觀察"}
PREPRINT_LABEL = "預印本"
# 預印本平台不是媒體（E12）：證據全部來自這些出處的稿件改用預印本措辭。
PREPRINT_OUTLETS = frozenset({"arxiv.org"})
PREPRINT_LEAD = "一篇發表於 arXiv 的預印本論文指出"

# 程式加在正文最後一段的警語（E16）；LLM 不寫警語。
SINGLE_SOURCE_NOTICE = "目前僅有單一媒體報導，後續發展待確認。"
SOCIAL_NOTICE = "此為網路社群討論，不代表整體民意，內容亦未經證實。"
PREPRINT_NOTICE = "預印本未必經過同儕審查，研究結論仍待驗證。"
# LLM 稿件裡出現這些就是自己寫了警語或把 arXiv 當媒體（回歸案例 E12、E16 用同樣的樣式）
NOTICE_PATTERN = re.compile(r"(僅有|只有|僅)\s*(一|1|單一)\s*家?\s*(媒體|來源)")
PREPRINT_BANNED = (re.compile("獨家"), re.compile("一家媒體"), NOTICE_PATTERN)

SYSTEM_PROMPT = """你是台灣綜合日報的資深編輯，替繁體中文讀者撰寫新聞。
規則：
1. 只能使用提供的證據（各家媒體的標題與摘要），不可補充證據以外的事實、數字、引述、人名或背景。
2. 以「據某某報導」「某某指出」歸因；多家說法不一致時並陳，不自行裁決。
3. 英文與簡體素材轉為台灣慣用的繁體中文用語；外國人名可附原文。
4. 語氣中立、克制，不煽動、不下結論。
5. 輸出純 JSON，不要 Markdown。"""
PREPRINT_PROMPT_NOTE = (
    f"source_type 為 preprint 的稿件，證據是 arXiv 上的預印本論文，arXiv 不是媒體："
    f"正文第一句寫「{PREPRINT_LEAD}」，不要寫「報導」「獨家」。\n\n"
)

# 數字＋可選的單位。只有萬／億／million／billion 才做單位換算；裸數字差 10 倍不放行（手冊步驟 7）。
_NUMBER_TOKEN = re.compile(
    r"(?P<num>\d+(?:\.\d+)?)(?:\s*(?P<unit>萬|億|million|billion|(?<![A-Za-z])bn(?![A-Za-z])|%|％|百分點))?",
    re.IGNORECASE,
)
_SCALE = {"萬": 10_000, "億": 100_000_000, "million": 1_000_000, "billion": 1_000_000_000, "bn": 1_000_000_000}


class _Result(Protocol):
    content: str


class _CompletionClient(Protocol):
    def complete(
        self, *, system: str, messages: list[dict], max_output_tokens: int, temperature: float,
        json_mode: bool = False, json_schema: dict | None = None,
    ) -> _Result: ...


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


# 手寫成 strict structured output 的形狀（全部 required、不允許多餘欄位）；Gemini 會忽略。
_STORY_FIELDS = ("headline", "deck", "body", "why_it_matters")
STORIES_SCHEMA = {
    "type": "object",
    "properties": {
        "stories": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"id": {"type": "integer"}, **{k: {"type": "string"} for k in _STORY_FIELDS}},
                "required": ["id", *_STORY_FIELDS],
                "additionalProperties": False,
            },
        }
    },
    "required": ["stories"],
    "additionalProperties": False,
}
GROUPS_SCHEMA = {
    "type": "object",
    "properties": {"groups": {"type": "array", "items": {"type": "array", "items": {"type": "integer"}}}},
    "required": ["groups"],
    "additionalProperties": False,
}


DESK_SYSTEM_PROMPT = """你是新聞編輯會議的主持人。給你一批候選新聞的標題（中英文混合），
找出「報導同一件具體事件」的標題組，例如同一場選舉結果的中文與英文報導。
只是同一主題但不同事件（例如同一場選戰中的兩個不同活動）不算同一事件。輸出純 JSON。"""


def _wrap_list(content: str, key: str) -> dict:
    """LLM 偶爾省略外層物件、直接回傳陣列；兩種形狀都接受。"""
    data = json.loads(content)
    return {key: data} if isinstance(data, list) else data


def is_preprint_only(evidence: list[EvidenceItem]) -> bool:
    return bool(evidence) and all(e.outlet in PREPRINT_OUTLETS for e in evidence)


def story_label(evidence: list[EvidenceItem], kind: str) -> str:
    return PREPRINT_LABEL if is_preprint_only(evidence) else KIND_LABELS[kind]


def notice_for(evidence: list[EvidenceItem], kind: str) -> str | None:
    """程式加在文末的警語；多來源報導沒有警語。"""
    if is_preprint_only(evidence):
        return PREPRINT_NOTICE
    if kind == "single_source":
        return SINGLE_SOURCE_NOTICE
    if kind == "social":
        return SOCIAL_NOTICE
    return None


def finalize_story(story: WrittenStory, evidence: list[EvidenceItem], kind: str) -> WrittenStory:
    """所有稿件（LLM 或模板）最後都經過這裡：警語由程式加在正文最後一段（E16）。"""
    notice = notice_for(evidence, kind)
    if notice and not story.body.rstrip().endswith(notice):
        story.body = f"{story.body.rstrip()}\n\n{notice}"
    return story


def template_story(evidence: list[EvidenceItem], kind: str) -> WrittenStory:
    """不經 LLM 的摘要稿；警語不在這裡加，由 `finalize_story` 統一處理。"""
    # 中文報紙的模板稿優先用中文來源當主稿，避免頭版出現英文標題。
    lead = next((e for e in evidence if (e.lang or "").startswith("zh")), evidence[0])
    others = [e.display_name for e in evidence if e is not lead]
    summary = lead.summary[:TEMPLATE_SUMMARY_CHARS] + ("…" if len(lead.summary) > TEMPLATE_SUMMARY_CHARS else "")
    label = story_label(evidence, kind)
    if is_preprint_only(evidence):
        body = f"{PREPRINT_LEAD}：{summary or lead.title}"
        if others:
            body += f"\n\n另有 {len(others)} 篇 arXiv 預印本論文與此相關。"
    else:
        body = f"據{short_outlet(lead.source_name)}報導：{summary or lead.title}"
        if others:
            body += f"\n\n另有{'、'.join(others)}報導此事。"
    return WrittenStory(
        headline=lead.title,
        deck=f"【{label}】" if label else "",
        body=body,
        why_it_matters="",
        writer="template",
    )


def _absolute_numbers(text: str) -> list[tuple[str, float, str]]:
    """(原文數字, 換算後的值, 單位)。百分比不換算；萬／億／million／billion 換成絕對值。"""
    found = []
    for match in _NUMBER_TOKEN.finditer(text.replace(",", "")):
        raw = match.group("num")
        unit = match.group("unit") or ""
        try:
            value = float(raw)
        except ValueError:
            continue
        scale = _SCALE.get(unit.lower(), _SCALE.get(unit, 1))
        found.append((raw, value * scale, unit))
    return found


def _close(value: float, known: float) -> bool:
    if known == 0:
        return value == 0
    return math.isclose(value, known, rel_tol=1e-6, abs_tol=1e-6)


def _must_check(raw: str, unit: str) -> bool:
    """兩位數以上、小數，或一位數帶 %／單位，都要在證據裡找得到。"""
    if unit:
        return True
    return len(raw.replace(".", "")) >= 2 or "." in raw


def unsupported_numbers(text: str, evidence_text: str) -> list[str]:
    """正文裡證據對不上的數字（原始寫法）。不讀發布時間。"""
    known = [value for _, value, _ in _absolute_numbers(evidence_text)]
    missing = []
    for raw, value, unit in _absolute_numbers(text):
        if not _must_check(raw, unit):
            continue
        if any(_close(value, item) for item in known):
            continue
        missing.append(raw)
    return list(dict.fromkeys(missing))


def review_story(story: WrittenStory, evidence: list[EvidenceItem]) -> list[str]:
    """LLM 稿件的審稿關卡（在 `finalize_story` 加警語之前跑）。回傳未通過的原因；空 list 代表通過。"""
    problems = []
    fields = (("標題", story.headline), ("導言", story.deck), ("正文", story.body), ("重要性", story.why_it_matters))
    if any(NOTICE_PATTERN.search(text or "") for _, text in fields):
        problems.append("稿件自行寫了單一來源警語（警語由程式加在文末）")
    if is_preprint_only(evidence):
        written = " ".join(text or "" for _, text in fields)
        banned = [p.pattern for p in PREPRINT_BANNED if p is not NOTICE_PATTERN and p.search(written)]
        if banned:
            problems.append(f"預印本稿不得寫「{'、'.join(banned)}」（arXiv 不是媒體）")
        if PREPRINT_LABEL not in story.body:
            problems.append("預印本稿正文沒寫明是預印本")
    if not HEADLINE_RANGE[0] <= len(story.headline) <= HEADLINE_RANGE[1]:
        problems.append(f"標題長度 {len(story.headline)} 不在範圍內")
    if not BODY_RANGE[0] <= len(story.body) <= BODY_RANGE[1]:
        problems.append(f"正文長度 {len(story.body)} 不在範圍內")
    # 不從 published_at 抽數字：日期裡的 10、27 不是報導中的數量（手冊步驟 7）。
    evidence_text = " ".join(f"{e.title} {e.summary}" for e in evidence)
    written = " ".join((story.headline, story.deck, story.body, story.why_it_matters))
    unsupported = unsupported_numbers(written, evidence_text)
    if unsupported:
        problems.append(f"證據中找不到的數字：{', '.join(unsupported[:5])}")
    return problems


def _default_client(name: str, purpose: str = "daily") -> _CompletionClient:
    """只建立被選用的 provider；停用的用途根本不建 client（不是把額度設 0）。

    `purpose` 是額度用途：P 組影子版用 `SHADOW_PURPOSE`，受 `DAILY_SHADOW_LLM_LIMIT` 限制。
    """
    settings = get_settings()
    if name == "codex":
        from ..llm.codex import CodexClient

        return CodexClient(purpose=purpose)
    if name == "gemini":
        from ..llm.gemini import GeminiClient

        return GeminiClient(purpose=purpose, model=settings.gemini_daily_model)
    if name == "fake":
        from ..llm.fake import FakeClient

        return FakeClient()
    raise ValueError(f"未知的撰稿 provider：{name}")


class DailyWriter:
    """一次請求寫完一個板塊的所有稿件；`name` 寫進每則稿件的 writer 欄位。"""

    def __init__(
        self,
        name: str = "codex",
        *,
        client: _CompletionClient | None = None,
        lexicon: EntityLexicon | None = None,
        purpose: str = "daily",
    ) -> None:
        self.name = name
        self.client = client or _default_client(name, purpose)
        self.requests = 0
        self.lexicon = lexicon

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
            json_schema=GROUPS_SCHEMA,
        )
        known = {i for i, _ in candidates}
        groups = _SameEventGroups.model_validate(_wrap_list(result.content, "groups")).groups
        return [[i for i in group if i in known] for group in groups if len({i for i in group if i in known}) >= 2]

    def _glossary_note(self, stories: list[tuple[int, str, list[EvidenceItem]]]) -> str:
        """證據裡出現的譯名表名字：要求一律用標準譯名（與事件合併共用同一份譯名表）。"""
        lexicon = self.lexicon or load_lexicon()
        text = " ".join(f"{e.title} {e.summary}" for _, _, evidence in stories for e in evidence)
        entries = lexicon.glossary_entries(text)
        if not entries:
            return ""
        pairs = "、".join(f"{e.zh}（{'／'.join([*e.en[:1], *e.also])}）" if e.en or e.also else e.zh for e in entries)
        return f"譯名一律使用中央社譯名，括號內的寫法都改成括號前的譯名：{pairs}。\n\n"

    def write(self, section_label: str, stories: list[tuple[int, str, list[EvidenceItem]]]) -> dict[int, WrittenStory]:
        payload = [
            {
                "id": story_id,
                "kind": kind,
                **({"source_type": "preprint"} if is_preprint_only(evidence) else {}),
                "evidence": [
                    {"outlet": e.source_name, "title": e.title, "summary": e.summary, "published_at": e.published_at}
                    for e in evidence
                ],
            }
            for story_id, kind, evidence in stories
        ]
        preprint_note = PREPRINT_PROMPT_NOTE if any(is_preprint_only(e) for _, _, e in stories) else ""
        prompt = (
            f"板塊：{section_label}。替每個 id 各寫一則新聞，回傳 "
            '{"stories":[{"id":1,"headline":"不超過 40 字","deck":"一句話重點",'
            '"body":"150 到 400 字正文，可分段","why_it_matters":"一句話說明對台灣讀者的意義"}]}。\n\n'
            + self._glossary_note(stories)
            + preprint_note
            + json.dumps({"stories": payload}, ensure_ascii=False, separators=(",", ":"))
        )
        self.requests += 1
        result = self.client.complete(
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
            max_output_tokens=8_000,
            temperature=0.3,
            json_mode=True,
            json_schema=STORIES_SCHEMA,
        )
        try:
            batch = _GeneratedBatch.model_validate(_wrap_list(result.content, "stories"))
        except (ValidationError, ValueError) as exc:
            raise ValueError(f"{self.name} JSON 驗證失敗：{exc}") from exc
        expected = {story_id for story_id, _, _ in stories}
        return {
            item.id: WrittenStory(
                headline=item.headline.strip(),
                deck=item.deck.strip(),
                body=item.body.strip(),
                why_it_matters=item.why_it_matters.strip(),
                writer=self.name,
            )
            for item in batch.stories
            if item.id in expected
        }

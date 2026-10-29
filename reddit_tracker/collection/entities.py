"""共同實體檢查（手冊步驟 3 第 1–4 點）：兩篇標題要有共同的人名、地名、組織名或數字才合併。

規格見 docs/v5/CLUSTERING.md「共同實體與兩段門檻」。只看標題，全部由程式判斷：

- 先用譯名表（`seeds/name_glossary.yaml`）把名字統一成中文標準譯名（Lula、露拉 → 魯拉）。
- 英文：大寫開頭的詞，但句首字與常見字（`seeds/entity_common_words.yaml`）不算；
  整個標題都是 Title Case 時只認譯名表的名字。句首字例外：當天其他標題在句中也把它
  大寫、而且當天從沒以小寫出現（例如「Anthropic files for IPO…」），才算名字。
- 中文：譯名表命中的名字，加上兩篇都有、3 個字以上、在當天素材標題中出現率 < 5% 的片段。
- 數字：3 位數以上（去掉千分位），但 1900–2100 的年份不算。

合併規則（`MergeRules`）：相似度 ≥ 高門檻要 ≥1 個共同實體；介於低門檻與高門檻要 ≥2 個；
低於低門檻不合併。
"""

from __future__ import annotations

import re
import unicodedata
from html import unescape
from collections import Counter
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Iterable

import yaml
import zhconv
from pydantic import BaseModel, Field

SEEDS_DIR = Path(__file__).resolve().parent.parent / "seeds"
DEFAULT_GLOSSARY_PATH = SEEDS_DIR / "name_glossary.yaml"
DEFAULT_COMMON_WORDS_PATH = SEEDS_DIR / "entity_common_words.yaml"

ZH_FRAGMENT_MIN_CHARS = 3
ZH_FRAGMENT_MAX_DF_RATIO = 0.05
# 只有這兩篇有的片段一定算少見；避免素材很少時（例如測試）5% 小於 1 篇而永遠不成立。
ZH_FRAGMENT_ALWAYS_RARE_DF = 2
NUMBER_MIN_DIGITS = 3
YEAR_RANGE = (1900, 2100)
TITLE_CASE_MIN_WORDS = 3
# Title Case 判斷時不看的小字（英文標題慣例小寫）
TITLE_SMALL_WORDS = frozenset(
    "a an the and or but nor of to in on at for by with from as vs via per into onto over up off "
    "out than after before amid about".split()
)

_CJK = "㐀-䶿一-鿿豈-﫿"
_CJK_RUN = re.compile(f"[{_CJK}]+")
_HAS_CJK = re.compile(f"[{_CJK}]")
_NUMBER = re.compile(r"\d[\d,]*\d|\d")
_LATIN_WORD = re.compile(r"[A-Za-z][A-Za-z0-9&'\-.]*[A-Za-z0-9]|[A-Za-z]|\x00")
# 句子分界：句點、問號、冒號、破折號等後面接空白，或「 - 」；後面的第一個字算句首字。
_SENTENCE_BREAK = re.compile(r"[.!?:;|–—]\s+|\s-\s|^\s*['\"‘“]")
_PLACEHOLDER = "\x00"


class GlossaryEntry(BaseModel):
    en: list[str] = Field(default_factory=list)
    zh: str
    also: list[str] = Field(default_factory=list)


def fold(text: str) -> str:
    """HTML 實體還原、NFKC、簡轉繁、去重音符號、統一撇號；英文與中文標題都走同一個正規化。"""
    text = zhconv.convert(unicodedata.normalize("NFKC", unescape(text or "")), "zh-tw")
    text = "".join(ch for ch in unicodedata.normalize("NFKD", text) if not unicodedata.combining(ch))
    return unicodedata.normalize("NFC", text).replace("’", "'").replace("‘", "'")


@dataclass(frozen=True)
class TitleEntities:
    names: frozenset[str]  # 譯名表標準中文名、英文專有名詞（小寫）、數字
    cjk: str  # 拿掉譯名表名字後剩下的中文（簡轉繁），用來找共同片段
    trigrams: frozenset[str]
    leads: frozenset[str] = frozenset()  # 大寫的句首字（要當天其他標題佐證才算名字）
    proper: frozenset[str] = frozenset()  # 句中大寫的英文字（佐證別篇的句首字）
    lower: frozenset[str] = frozenset()  # 小寫出現的英文字（反證：是一般字）


@dataclass(frozen=True)
class MergeRules:
    """事件合併門檻（手冊步驟 3 第 2 點）；數值來自設定（`config.Settings.cluster_*`）。"""

    high_threshold: float = 0.45
    low_threshold: float = 0.28
    high_min_entities: int = 1
    mid_min_entities: int = 2
    # 編輯會議：程式自己做的跨語言合併（沒有相似度分數）要幾個共同實體
    cross_lang_min_entities: int = 2
    # 編輯會議：find_same_events（LLM 第二意見）說要合併時，程式要確認幾個共同實體
    llm_merge_min_entities: int = 1

    @classmethod
    def from_settings(cls, settings=None) -> MergeRules:
        if settings is None:
            from ..config import get_settings

            settings = get_settings()
        return cls(
            high_threshold=settings.cluster_high_threshold,
            low_threshold=settings.cluster_low_threshold,
            high_min_entities=settings.cluster_high_min_entities,
            mid_min_entities=settings.cluster_mid_min_entities,
            cross_lang_min_entities=settings.cluster_cross_lang_min_entities,
            llm_merge_min_entities=settings.cluster_llm_merge_min_entities,
        )

    def required_entities(self, score: float) -> int | None:
        """相似度 `score` 要幾個共同實體才合併；None 代表不合併。"""
        if score >= self.high_threshold:
            return self.high_min_entities
        if score >= self.low_threshold:
            return self.mid_min_entities
        return None


def _alternation(patterns: Iterable[str]) -> str:
    return "|".join(re.escape(p) for p in sorted(set(patterns), key=len, reverse=True))


class EntityLexicon:
    """譯名表＋常見字清單；`entities()` 抽出一個標題的實體，`shared()` 比兩個標題。"""

    def __init__(self, glossary: list[GlossaryEntry], common_words: Iterable[str]) -> None:
        self.glossary = glossary
        self.common_words = frozenset(fold(w).lower().strip() for w in common_words)
        canonical: dict[str, str] = {}
        for entry in glossary:
            for variant in [*entry.en, entry.zh, *entry.also]:
                key = fold(variant).lower()
                if canonical.setdefault(key, entry.zh) != entry.zh:
                    raise ValueError(f"譯名表重複的寫法：{variant}（{canonical[key]}／{entry.zh}）")
        self._canonical = canonical
        latin = [k for k in canonical if not _HAS_CJK.search(k)]
        cjk = [k for k in canonical if _HAS_CJK.search(k)]
        # 英文名字要整個字符合（Xi 不能比對到 Xinjiang）；中文名字直接比對子字串。
        parts = []
        if latin:
            parts.append(f"(?<![A-Za-z0-9])(?:{_alternation(latin)})(?![A-Za-z0-9])")
        if cjk:
            parts.append(f"(?:{_alternation(cjk)})")
        self._names = re.compile("|".join(parts), re.IGNORECASE) if parts else None
        self.entities = lru_cache(maxsize=65_536)(self._entities)

    # ── 抽取 ────────────────────────────────────────────────────────────

    def glossary_names(self, text: str) -> list[str]:
        """文字中出現的譯名表標準中文名（依出現順序、不重複）。"""
        if self._names is None:
            return []
        return list(dict.fromkeys(self._canonical[m.group(0).lower()] for m in self._names.finditer(fold(text))))

    def glossary_entries(self, text: str) -> list[GlossaryEntry]:
        wanted = set(self.glossary_names(text))
        return [entry for entry in self.glossary if entry.zh in wanted]

    def _entities(self, title: str, is_zh: bool) -> TitleEntities:
        text = fold(title)
        names: set[str] = set()
        if self._names is not None:
            for match in self._names.finditer(text):
                names.add(self._canonical[match.group(0).lower()])
            text = self._names.sub(f" {_PLACEHOLDER} ", text)
        for raw in _NUMBER.findall(text):
            digits = raw.replace(",", "")
            if len(digits) >= NUMBER_MIN_DIGITS and not (
                len(digits) == 4 and YEAR_RANGE[0] <= int(digits) <= YEAR_RANGE[1]
            ):
                names.add(digits.lstrip("0") or "0")
        leads: set[str] = set()
        proper: set[str] = set()
        lower = frozenset(w.lower() for w in _LATIN_WORD.findall(text) if w[0].islower())
        if is_zh or _HAS_CJK.search(text):
            names.update(self._latin_names_in_cjk(text))
        else:
            proper, leads = self._english_proper_nouns(text)
            names.update(proper)
        cjk = " ".join(_CJK_RUN.findall(text))
        trigrams = frozenset(
            run[i : i + ZH_FRAGMENT_MIN_CHARS]
            for run in cjk.split()
            for i in range(len(run) - ZH_FRAGMENT_MIN_CHARS + 1)
        )
        return TitleEntities(frozenset(names), cjk, trigrams, frozenset(leads), frozenset(proper), lower)

    def _word_key(self, word: str) -> str | None:
        key = word.lower()
        if key.endswith("'s"):
            key = key[:-2]
        key = key.strip("'-.")
        if len(key) < 2 or key in self.common_words or key.isdigit():
            return None
        return key

    def _latin_names_in_cjk(self, text: str) -> set[str]:
        """中文標題裡的英文字（SpaceX、Anthropic）幾乎都是名字；大寫開頭、不是常見字就算。"""
        keys = set()
        for word in _LATIN_WORD.findall(text):
            if word != _PLACEHOLDER and any(ch.isupper() for ch in word):
                key = self._word_key(word)
                if key:
                    keys.add(key)
        return keys

    def _english_proper_nouns(self, text: str) -> tuple[set[str], set[str]]:
        """回傳（句中大寫的專有名詞, 句首的大寫字）。"""
        words = [w for w in _LATIN_WORD.findall(text) if w != _PLACEHOLDER]
        content = [w for w in words if w.lower() not in TITLE_SMALL_WORDS]
        if len(content) >= TITLE_CASE_MIN_WORDS and all(_capitalized(w) for w in content):
            return set(), set()  # Title Case：每個字都大寫，看不出哪些是名字，只認譯名表
        keys, leads = set(), set()
        for segment in _SENTENCE_BREAK.split(text):
            for position, word in enumerate(_LATIN_WORD.findall(segment)):
                if word == _PLACEHOLDER or not _capitalized(word):
                    continue
                key = self._word_key(word)
                if key:
                    # 句首字一律大寫，不代表是名字；iPhone、eBay 這種大小寫混合的字本身就是名字
                    (leads if position == 0 and not _mixed_case(word) else keys).add(key)
        return keys, leads - keys

    # ── 比對 ────────────────────────────────────────────────────────────

    def shared(self, a: TitleEntities, b: TitleEntities, context: EntityContext | None) -> set[str]:
        """兩個標題的共同實體：共同名字＋（都有中文時）共同的少見中文片段。"""
        if context is None:
            common = set(a.names & b.names)
        else:
            common = context.names(a) & context.names(b)
        if context is not None and a.trigrams and b.trigrams:
            rare = {t for t in a.trigrams & b.trigrams if context.is_rare(t)}
            if rare:
                common.update(f"「{fragment}」" for fragment in _covered_runs(a.cjk, rare))
        return common


class EntityContext:
    """「當天素材」的統計：中文三字片段出現篇數（判斷是否 < 5%）與英文句首字的佐證。"""

    def __init__(self, titles: Iterable[TitleEntities], max_df_ratio: float = ZH_FRAGMENT_MAX_DF_RATIO) -> None:
        self.df: Counter = Counter()
        self.total = 0
        proper: set[str] = set()
        lower: set[str] = set()
        for title in titles:
            self.total += 1
            self.df.update(title.trigrams)
            proper |= title.proper
            lower |= title.lower
        self.max_df = max_df_ratio * self.total
        self.proper_nouns = frozenset(proper - lower)

    def names(self, title: TitleEntities) -> set[str]:
        return set(title.names) | (title.leads & self.proper_nouns)

    def is_rare(self, trigram: str) -> bool:
        df = self.df.get(trigram, 0)
        return df <= ZH_FRAGMENT_ALWAYS_RARE_DF or df < self.max_df


def _capitalized(word: str) -> bool:
    return word[0].isupper() or _mixed_case(word)


def _mixed_case(word: str) -> bool:
    """字中間有大寫、也有小寫（iPhone、eBay、SpaceX）。"""
    return any(ch.isupper() for ch in word[1:]) and any(ch.islower() for ch in word)


def _covered_runs(cjk: str, trigrams: set[str]) -> list[str]:
    """`cjk` 中被共同三字片段覆蓋的最長連續段；每段算一個實體。"""
    n = ZH_FRAGMENT_MIN_CHARS
    covered = [False] * len(cjk)
    for i in range(len(cjk) - n + 1):
        if cjk[i : i + n] in trigrams:
            for j in range(i, i + n):
                covered[j] = True
    runs, start = [], None
    for i, flag in enumerate([*covered, False]):
        if flag and start is None:
            start = i
        elif not flag and start is not None:
            runs.append(cjk[start:i])
            start = None
    return list(dict.fromkeys(runs))


def load_glossary(path: str | Path = DEFAULT_GLOSSARY_PATH) -> list[GlossaryEntry]:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or []
    return [GlossaryEntry.model_validate(row) for row in data]


def load_common_words(path: str | Path = DEFAULT_COMMON_WORDS_PATH) -> list[str]:
    return [str(word) for word in yaml.safe_load(Path(path).read_text(encoding="utf-8")) or []]


@lru_cache(maxsize=8)
def _load_lexicon(glossary_path: str, common_words_path: str) -> EntityLexicon:
    return EntityLexicon(load_glossary(glossary_path), load_common_words(common_words_path))


def load_lexicon(glossary_path: str | Path | None = None, common_words_path: str | Path | None = None) -> EntityLexicon:
    """預設路徑來自設定（`NAME_GLOSSARY_PATH`、`ENTITY_COMMON_WORDS_PATH`）。"""
    if glossary_path is None or common_words_path is None:
        from ..config import get_settings

        settings = get_settings()
        glossary_path = glossary_path or settings.name_glossary_path
        common_words_path = common_words_path or settings.entity_common_words_path
    return _load_lexicon(str(glossary_path), str(common_words_path))

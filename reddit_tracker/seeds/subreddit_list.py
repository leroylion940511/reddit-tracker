"""Initial subreddit seeds for discovery layer.

對應企劃書 §三 — 目標 12–20 個 sub，中英混合。M2 的 seeds/loader.py 會把
這份清單冪等寫入 `subreddit_sources` 表，之後可在 DB 端用 enabled 開關。

挑選原則：
- 中文 sub：流量足夠且素人投稿密集（r/Taiwan、r/HongKong）。學術 / 翻譯類
  （r/ChineseLanguage、r/translator）流量低但語料品質佳，先放著觀察。
- 英文 sub：偏 storytelling / 事件型，命中「素人爆文」命題；尤其
  r/BestofRedditorUpdates 本身就在彙整有後續發展的事件，是 v4 「四類後續事件」
  研究主題的天然樣本來源。
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class SubredditSeed:
    name: str           # 不含 r/ 前綴
    language: str       # zh / en
    category: str
    note: str = ""


SUBREDDIT_SEEDS: list[SubredditSeed] = [
    # --- 中文 ---
    SubredditSeed("Taiwan", "zh", "regional", "台灣綜合，最大中文素人爆文池"),
    SubredditSeed("HongKong", "zh", "regional", "香港中文 + 英文混雜"),
    SubredditSeed("China_irl", "zh", "regional", "中國時事 / 生活，發文量穩定"),
    SubredditSeed("taipei", "zh", "regional", "台北地方，事件型貼文密度高"),
    SubredditSeed("ChineseLanguage", "zh", "language", "語言學習，補語料用"),

    # --- 英文 storytelling / 事件 ---
    SubredditSeed("tifu", "en", "story", "Today I Fucked Up，自述事件第一手素材"),
    SubredditSeed("relationship_advice", "en", "story", "感情 drama，後續發展密度極高"),
    SubredditSeed("AmItheAsshole", "en", "story", "倫理判斷型，留言互動極熱"),
    SubredditSeed("confession", "en", "story", "匿名告解，事件型短文"),
    SubredditSeed("offmychest", "en", "story", "情緒宣洩，部分含後續更新"),
    SubredditSeed("BestofRedditorUpdates", "en", "meta", "彙整有後續的事件，研究『四類後續』的金礦"),
    SubredditSeed("MaliciousCompliance", "en", "story", "故事性強、結尾有 punchline"),
    SubredditSeed("UpdateMe", "en", "meta", "讀者追更工具 sub，可推測哪些貼文有後續"),
    SubredditSeed("legaladvice", "en", "advice", "法律諮詢，事件型 + 後續發展明確"),
    SubredditSeed("AskReddit", "en", "general", "問答海量，作為對照組（預期評分通過率低）"),
]


def enabled_seeds() -> list[SubredditSeed]:
    """M1 階段全部啟用；M7 評估後會在 DB 端關掉效益低的 sub。"""
    return SUBREDDIT_SEEDS

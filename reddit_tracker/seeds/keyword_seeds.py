"""Initial keyword seeds for cross-subreddit search (every 6h job).

對應 SCHEDULE.md M1.10 + M2.10。中英文各 10 詞，挑選原則：
- 偏「事件 / 後續 / 求助」語意，與素人爆文命題對齊
- 避開太通用的詞（the / a / 是 / 的）— 這些命中過多雜訊
- 中文以繁體為主、簡體為輔；Reddit search 對中文分詞較弱，保留多種寫法

關鍵字會餵進 `reddit.subreddit("all").search(keyword, time_filter="day")`。
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class KeywordSeed:
    term: str
    language: str       # zh / en
    intent: str         # update / drama / help / discovery
    note: str = ""


KEYWORD_SEEDS: list[KeywordSeed] = [
    # --- 中文：事件 / 後續 ---
    KeywordSeed("更新", "zh", "update", "中文 update 慣用詞"),
    KeywordSeed("後續", "zh", "update", ""),
    KeywordSeed("結果", "zh", "update", "事件收尾常見開頭"),
    KeywordSeed("求助", "zh", "help", ""),
    KeywordSeed("怎麼辦", "zh", "help", "情緒求助"),
    KeywordSeed("抓到", "zh", "drama", "外遇 / 抓包類"),
    KeywordSeed("分手", "zh", "drama", ""),
    KeywordSeed("公司", "zh", "discovery", "職場事件入口"),
    KeywordSeed("老闆", "zh", "drama", "職場衝突"),
    KeywordSeed("被開除", "zh", "drama", ""),

    # --- 英文：事件 / 後續 ---
    KeywordSeed("UPDATE", "en", "update", "Reddit 標題慣例全大寫"),
    KeywordSeed("aftermath", "en", "update", ""),
    KeywordSeed("found out", "en", "drama", "外遇 / 揭穿模板"),
    KeywordSeed("caught", "en", "drama", ""),
    KeywordSeed("exposed", "en", "drama", ""),
    KeywordSeed("fired", "en", "drama", "職場"),
    KeywordSeed("WIBTA", "en", "help", "AITA 變體"),
    KeywordSeed("dilemma", "en", "help", ""),
    KeywordSeed("confession", "en", "discovery", "告解類入口"),
    KeywordSeed("blew up", "en", "drama", "事件爆發語意"),
]


def enabled_seeds() -> list[KeywordSeed]:
    return KEYWORD_SEEDS

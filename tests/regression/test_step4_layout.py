"""手冊步驟 4 做完的標準，在離線重編的 10/27 上驗證（錄音重播，不呼叫真 LLM）。"""

from __future__ import annotations

from collections import Counter
from html import escape

from reddit_tracker.daily.scoring import SECTION_QUOTAS


def test_exactly_twelve_articles_with_six_front_marked_among_them(rebuilt):
    published = rebuilt.published
    assert len(published) == 12
    assert Counter(s.section for s in published) == Counter(SECTION_QUOTAS)  # 台灣、國際、科技各 4
    assert sum(s.is_front for s in published) == 6
    assert rebuilt.stats["articles"] == 12 and rebuilt.stats["front_articles"] == 6


def test_cross_strait_and_finance_stories_land_in_inner_sections(rebuilt):
    """兩岸、財經事件全部改寫到三個內版去競爭配額，不會整篇消失。

    10/27 財經稿有刊出（柯米→國際、微軟／SpaceX→科技）；兩岸事件全部改到台灣／國際版參與選題，
    但分數沒擠進國際版前 4 名（照分數，不硬塞）。
    """
    rewrites = rebuilt.stats["section_rewrites"]
    targets = {key.split("→")[1] for key in rewrites}
    assert targets <= set(SECTION_QUOTAS) | {"taiwan"}
    assert any(k.startswith("cross_strait→") for k in rewrites) and any(k.startswith("finance→") for k in rewrites)
    origins = Counter((s.signals or {}).get("original_section") for s in rebuilt.published)
    assert origins["finance"] >= 1
    assert all(story.section in SECTION_QUOTAS for story in rebuilt.published)
    candidates = [s for s in rebuilt.events if not s.published]
    assert not [s for s in candidates if s.section in ("cross_strait", "finance")]


def test_briefs_are_headlines_only_and_cost_no_llm_calls(rebuilt):
    briefs = rebuilt.stats["briefs"]
    assert briefs and {b["section"] for b in briefs} <= {"science_health", "life_env", "culture", "sports"}
    assert all(b["headline"] and b["url"] for b in briefs)
    # 撰稿請求只有頭版＋三個內版（編輯會議另計 1 次）；短訊 0 次
    assert rebuilt.stats["llm_requests"] <= 1 + 1 + len(SECTION_QUOTAS)
    front_html = rebuilt.html.split('id="front"')[1].split('id="taiwan"')[0]
    assert all(escape(b["headline"]) in front_html for b in briefs)


def test_inner_sections_link_front_stories_instead_of_rewriting(rebuilt):
    for story in (s for s in rebuilt.published if s.is_front):
        cluster_id = story.key.split(":")[1].split("+")[0]
        section_html = rebuilt.html.split(f'id="{story.section}"')[1].split('<h2 class="section"')[0]
        assert f'href="#story-{cluster_id}"' in section_html
        assert rebuilt.html.count(f'<article id="story-{cluster_id}">') == 1

"""M7.6 retune — 確保新版 SYSTEM_PROMPT 含關鍵盲點修補段落，且 JSON
schema 與 parser 介面沒被破壞。

對應 docs/m7_haiku_fail_analysis.md 的 retune 提案。
"""

from __future__ import annotations

from reddit_tracker.llm.haiku import (
    SYSTEM_PROMPT,
    build_user_prompt,
    parse_haiku_response,
    verdict_from_payload,
)
from reddit_tracker.models import CandidatePost


# ---------------------------------------------------------------------------
# SYSTEM_PROMPT 內容檢查（fixture-based snapshot，不打 API）
# ---------------------------------------------------------------------------


def test_prompt_includes_topical_story_potential_clause():
    """story_potential 定義要明確涵蓋議題型，不只事件型 — 否則中文 sub
    議題討論貼會被低估（fail_analysis §2.2）。"""
    assert "議題能持續引發討論" in SYSTEM_PROMPT or "議題型" in SYSTEM_PROMPT
    # 條件式說明：emotional_pull + authenticity 夠高時，議題即構成 story_potential
    assert "emotional_pull" in SYSTEM_PROMPT
    assert "authenticity" in SYSTEM_PROMPT


def test_prompt_warns_about_zero_traffic_evidence():
    """0/0 互動數據 disclaimer — RSS source 跟 /new 端剛發布貼文都是 0/0
    起點，不該被 Haiku 當冷度證據（fail_analysis §2.3）。"""
    # 容忍多種表達方式
    text = SYSTEM_PROMPT
    assert "Score / Comments: 0 / 0" in text or "尚未累積互動" in text
    assert "時間序起點" in text or "剛發布" in text or "剛發佈" in text


def test_prompt_json_schema_preserved():
    """5 軸 + verdict + reason 七個欄位沒被改動 — parser 介面穩定。"""
    for axis in ("story_potential", "emotional_pull", "grassroots", "novelty", "authenticity"):
        assert axis in SYSTEM_PROMPT
    assert '"track"' in SYSTEM_PROMPT
    assert '"skip"' in SYSTEM_PROMPT
    assert '"reason"' in SYSTEM_PROMPT


def test_prompt_verdict_threshold_unchanged():
    """retune 不動 verdict 門檻 — story_potential ≥ 0.5 + authenticity ≥ 0.4 +
    avg ≥ 0.55 維持原樣。"""
    assert "≥ 0.55" in SYSTEM_PROMPT
    assert "story_potential ≥ 0.5" in SYSTEM_PROMPT
    assert "authenticity ≥ 0.4" in SYSTEM_PROMPT


# ---------------------------------------------------------------------------
# build_user_prompt 行為（未被 retune 動到，但加 regression）
# ---------------------------------------------------------------------------


def test_build_user_prompt_still_emits_score_zero_for_rss_source():
    """retune 決定不動 build_user_prompt — 0 互動仍透明傳給 Haiku，由 prompt
    自己處理。確認 wiring 沒被破壞。"""
    post = CandidatePost(
        reddit_post_id="abc1",
        subreddit="taiwan",
        title="議題：colleague 的更新",
        selftext="discussion body",
        author_username="anon",
        author_karma=None,
        upvote_ratio=None,
        initial_score=0,
        initial_num_comments=0,
    )
    text = build_user_prompt(post)
    assert "Subreddit: r/taiwan" in text
    assert "Score / Comments: 0 / 0" in text
    assert "(karma: unknown)" in text
    assert "Upvote ratio: unknown" in text


# ---------------------------------------------------------------------------
# parse / verdict — retune 後 parser 行為不變
# ---------------------------------------------------------------------------


def test_parser_still_handles_track_verdict_after_retune():
    raw = (
        '{"story_potential": 0.55, "emotional_pull": 0.75, "grassroots": 0.8, '
        '"novelty": 0.5, "authenticity": 0.7, "verdict": "track", '
        '"reason": "議題型討論有持續共鳴潛力"}'
    )
    data = parse_haiku_response(raw)
    v = verdict_from_payload(data)
    assert v.verdict == "track"
    assert v.story_potential == 0.55
    assert v.emotional_pull == 0.75

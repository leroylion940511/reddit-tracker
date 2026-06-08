"""M7.6 變體 — 抽 haiku-fail records 的 verdict reason 樣本。

SCHEDULE.md 7.6 字面是「分析 dislike / mute 樣本」, 但目前 dislike 只有
5 筆 (要 OAuth 累積). 改用 scoring 視角的等價分析:
    中文 sub haiku pass 15.1% vs 英文 35.3% (差 2.3×),
    抽 haiku-fail 的 reason / 五軸看 prompt 失準模式.

對應 [[project_m7_retune_backlog]] #1 (中文 haiku prompt 識別偏弱).

用法:
    uv run python scripts/eval_haiku_fail_samples.py > docs/m7_haiku_fail_samples.md
"""

from __future__ import annotations

import json
import sys
import textwrap
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import func, select, text  # noqa: E402

from reddit_tracker.db import session_scope  # noqa: E402
from reddit_tracker.models import CandidatePost, ScoringRecord  # noqa: E402


# 抽樣設計: 中文 sub 各 10 筆 fail, 英文對照 amitheasshole/offmychest 各 5 筆
ZH_SUBS = ["china_irl", "chineselanguage", "hongkong", "taipei", "taiwan"]
EN_SUBS_CONTROL = ["amitheasshole", "offmychest"]

ZH_PER_SUB = 10
EN_PER_SUB = 5


def _trunc(text: str | None, n: int) -> str:
    if not text:
        return "(empty)"
    text = text.replace("\n", " ").strip()
    if len(text) <= n:
        return text
    return text[: n - 1] + "…"


def _sample_fails(s, sub: str, n: int) -> list[tuple[CandidatePost, ScoringRecord]]:
    """從該 sub 抽 n 筆「實際被 haiku judge 為 skip」的 record。

    排除 rules-stage fail 的 placeholder row（details 帶 skipped_due_to_rules=true，
    代表 haiku 根本沒被呼叫）。
    """
    rows = s.execute(
        select(CandidatePost, ScoringRecord)
        .join(ScoringRecord, ScoringRecord.candidate_post_id == CandidatePost.id)
        .where(
            CandidatePost.subreddit == sub,
            ScoringRecord.stage == "haiku",
            ScoringRecord.passed.is_(False),
            # SQLite JSON1：placeholder row 帶 {"skipped_due_to_rules": true}
            text("json_extract(scoring_records.details, '$.skipped_due_to_rules') IS NULL"),
        )
        .order_by(func.random())
        .limit(n)
    ).all()
    return [(r[0], r[1]) for r in rows]


def _render_sample(label: str, sub: str, samples: list) -> None:
    print(f"\n### r/{sub} ({label}, {len(samples)} 筆)\n")
    if not samples:
        print("_no records_\n")
        return
    for cand, rec in samples:
        details = rec.details or {}
        if isinstance(details, str):
            try:
                details = json.loads(details)
            except Exception:
                details = {"raw": details[:200]}
        axes = " ".join(
            f"{k}={details.get(k, '—'):.2f}" if isinstance(details.get(k), (int, float)) else f"{k}=—"
            for k in ("story_potential", "emotional_pull", "grassroots", "novelty", "authenticity")
        )
        reason = _trunc(details.get("reason"), 160)
        title = _trunc(cand.title, 80)
        body = _trunc(cand.selftext, 120)
        print(f"- **[{cand.id}]** {title}")
        print(f"  - body: {body}")
        print(f"  - axes: {axes}  →  verdict=skip  score={rec.score:.3f}" if rec.score is not None else f"  - axes: {axes}  →  verdict=skip")
        print(f"  - reason: {reason}")


def main() -> None:
    with session_scope() as s:
        print("# M7.6 — Haiku-fail 樣本分析（中英對照）\n")
        print(textwrap.dedent("""\
            目的：scoring 視角下，找中文 sub haiku pass 15.1% vs 英文 35.3% 的失準模式。
            每個樣本顯示：title + body 截斷 + 五軸 + verdict reason。

            ## 中文 sub haiku-fail 樣本（4 sub × 10 + 1 sub × 10）
            """).rstrip())

        for sub in ZH_SUBS:
            samples = _sample_fails(s, sub, ZH_PER_SUB)
            _render_sample("zh fail", sub, samples)

        print("\n## 英文 sub haiku-fail 樣本（對照組）")
        for sub in EN_SUBS_CONTROL:
            samples = _sample_fails(s, sub, EN_PER_SUB)
            _render_sample("en fail", sub, samples)


if __name__ == "__main__":
    main()

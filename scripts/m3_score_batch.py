"""跑一輪 scoring，把目前 DB 內所有未評分 candidate 評到完。

用法：
    uv run python scripts/m3_score_batch.py

無 ANTHROPIC_API_KEY 時自動 fallback 到 FakeScorer（log warning）。
"""

from __future__ import annotations

import logging
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from reddit_tracker.config import get_settings  # noqa: E402
from reddit_tracker.db import session_scope  # noqa: E402
from reddit_tracker.llm.factory import build_scorer  # noqa: E402
from reddit_tracker.services.scoring import ScoringService, score_batch  # noqa: E402


def main() -> int:
    settings = get_settings()
    logging.basicConfig(
        level=settings.log_level,
        format="%(asctime)s %(levelname)s %(name)s | %(message)s",
    )
    log = logging.getLogger("m3_score_batch")

    service = ScoringService(scorer=build_scorer())

    total_scored = 0
    while True:
        with session_scope() as session:
            outcomes = score_batch(session, service, limit=settings.scoring_batch_limit)
        if not outcomes:
            break
        total_scored += len(outcomes)
        verdicts = Counter(o.haiku_verdict for o in outcomes)
        log.info(
            "batch done: %d (cumulative=%d) verdict_dist=%s rules_fail=%d errors=%d",
            len(outcomes),
            total_scored,
            dict(verdicts),
            sum(1 for o in outcomes if not o.rules_passed),
            sum(1 for o in outcomes if o.error),
        )
        if len(outcomes) < settings.scoring_batch_limit:
            break

    log.info("done. total scored=%d", total_scored)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

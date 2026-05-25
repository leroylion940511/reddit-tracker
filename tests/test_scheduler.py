"""Bug-B regression — scheduler initial pass 韌性。

2026-05-24 incident：`_run_keyword_discovery` 撞 UNIQUE constraint integrity
error，未被 catch，整支 scheduler process 死掉 → 過去 24h 0 個 scheduled
job 跑。

`run_initial_pass()` 每支 job 用獨立 try/except 包，單支死不影響其他、
也不會把 process 帶下水。
"""

from __future__ import annotations

from unittest.mock import patch

from reddit_tracker import scheduler


def test_initial_pass_all_ok():
    with (
        patch.object(scheduler, "_run_subreddit_discovery") as a,
        patch.object(scheduler, "_run_keyword_discovery") as b,
        patch.object(scheduler, "_run_scoring") as c,
    ):
        # 重新組 jobs tuple 引用打 patched callable
        with patch.object(
            scheduler,
            "INITIAL_PASS_JOBS",
            [
                ("subreddit_discovery", a),
                ("keyword_discovery", b),
                ("scoring", c),
            ],
        ):
            results = scheduler.run_initial_pass()
    assert results == {
        "subreddit_discovery": "ok",
        "keyword_discovery": "ok",
        "scoring": "ok",
    }
    a.assert_called_once()
    b.assert_called_once()
    c.assert_called_once()


def test_initial_pass_one_failing_doesnt_block_others():
    """keyword_discovery 炸不該阻擋 subreddit_discovery 跟 scoring。"""

    def boom():
        raise RuntimeError("UNIQUE constraint failed (simulated)")

    with (
        patch.object(scheduler, "_run_subreddit_discovery") as a,
        patch.object(scheduler, "_run_scoring") as c,
    ):
        with patch.object(
            scheduler,
            "INITIAL_PASS_JOBS",
            [
                ("subreddit_discovery", a),
                ("keyword_discovery", boom),
                ("scoring", c),
            ],
        ):
            results = scheduler.run_initial_pass()

    assert results["subreddit_discovery"] == "ok"
    assert "error:" in results["keyword_discovery"]
    assert "UNIQUE constraint" in results["keyword_discovery"]
    assert results["scoring"] == "ok"
    # subreddit + scoring 都實際被 call
    a.assert_called_once()
    c.assert_called_once()


def test_initial_pass_all_failing_still_returns():
    """全部都炸也不該 raise — 後續 scheduled job 仍有機會跑。"""

    def boom1():
        raise RuntimeError("boom1")

    def boom2():
        raise ValueError("boom2")

    def boom3():
        raise OSError("boom3")

    with patch.object(
        scheduler,
        "INITIAL_PASS_JOBS",
        [
            ("subreddit_discovery", boom1),
            ("keyword_discovery", boom2),
            ("scoring", boom3),
        ],
    ):
        results = scheduler.run_initial_pass()
    assert all(v.startswith("error:") for v in results.values())

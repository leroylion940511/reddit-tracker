"""P3-3：拆 orchestrator.py 之後，舊的 `orchestrator.X` 名稱仍指向同一個物件。"""

from reddit_tracker.daily.mas import orchestrator, prompts

PROMPT_NAMES = [n for n in vars(prompts) if n.isupper()]


def test_prompts_module_has_all_role_prompts():
    for name in ("REPORTER_SYSTEM", "CHECKER_SYSTEM", "EIC_SYSTEM", "COPY_SYSTEM", "PITCH_SYSTEM",
                 "OPEN_PITCH_SYSTEM", "APPEAL_SYSTEM", "PAGE_REVIEW_SYSTEM"):
        assert name in PROMPT_NAMES


def test_orchestrator_reexports_prompts_by_identity():
    assert len(PROMPT_NAMES) == 32
    for name in PROMPT_NAMES:
        assert getattr(orchestrator, name) is getattr(prompts, name), name


def test_prompts_module_has_no_runtime_dependencies():
    # 提示詞模組只放常數，不能反過來 import orchestrator（避免循環匯入）
    src = open(prompts.__file__, encoding="utf-8").read()
    assert "import" not in src.replace("from __future__ import annotations", "")

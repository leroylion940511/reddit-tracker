"""P3-3：拆 orchestrator.py 之後（prompts.py、checks.py），舊的 `orchestrator.X` 名稱仍指向同一個物件。"""

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


CHECK_NAMES = [
    "CHECKER_MIN_ZH_FRAGMENTS", "FRONT_CAPACITY", "INJECTION_MARKERS", "Pitch", "_Checker", "_Decision",
    "_Draft", "_decision_problems", "_evidence_text", "_has_marker", "_parse", "_percent_values", "_sid",
    "_usable_fulltext", "checker_says_same_event", "checker_source_verdicts", "evidence_has_injection",
    "guard_pitches", "irrelevant_sources",
]


def test_orchestrator_reexports_checks_by_identity():
    from reddit_tracker.daily.mas import checks

    for name in CHECK_NAMES:
        assert getattr(orchestrator, name) is getattr(checks, name), name


def test_checks_module_does_not_import_orchestrator_or_db():
    # 純判斷模組：不碰 DB、不呼叫模型，也不能反過來 import orchestrator（避免循環匯入）
    from reddit_tracker.daily.mas import checks

    imports = [line for line in open(checks.__file__, encoding="utf-8") if line.startswith(("import ", "from "))]
    for banned in ("orchestrator", "sqlalchemy", "llm", "models", "store"):
        assert not any(banned in line for line in imports), banned

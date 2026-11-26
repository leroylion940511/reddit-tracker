"""實驗二：查核員開與關的三組執行（手冊 8.2）。設計見 docs/eval/EXP2_DESIGN.md。

    # 1. 凍結案例（不呼叫模型；只讀唯讀快照與 production DB）
    uv run python scripts/run_exp2.py build --normal-ids 101,102,... --sample-dates 2026-11-09,...（A 選的 15 篇 story id；
    #    --sample-dates 與給 A 清單時的 sample_exp2.py --dates 相同，會檢查選稿都在 25 篇候選裡）
    # 2. 記者 v1，只產生一次（每篇 1 次 Codex）
    uv run python scripts/run_exp2.py draft --live
    # 3. 跑三組（已成功的呼叫從帳本重播，重跑不重複花額度）
    uv run python scripts/run_exp2.py run --arm all --live
    # 4. 結果表
    uv run python scripts/run_exp2.py report            # 印到 stdout
    uv run python scripts/run_exp2.py report --write    # 寫 docs/eval/exp2_results.md
    #    （舊檔 exp2.MANUAL_MARKER 那行以下的手寫分析原樣保留；有手寫小節卻沒標記就停）

    # 5. 課後補充消融 (c+)：逐來源判斷，只重跑指定案例；正式 (a)(b)(c) 的檔案不會被改
    uv run python scripts/run_exp2.py ablation --work-dir <複本目錄> --cases E02,H-T767 --live
    uv run python scripts/run_exp2.py ablation-report --work-dir <複本目錄>   # 印 Markdown，自己貼進報告的手寫段落

- `--work-dir`（每個子命令都有）：改用別的工作目錄（要先放 `cases.json`、`v1.json`，
  `ablation-report` 另要正式的 `results_c.json`）。`ablation` 一定要給，避免寫進正式結果的目錄。
- 所有產出都在 `data/work/exp2/`（不進版控）：`cases.json`、`v1.json`、`results_<組>.json`、
  帳本 `ledger.db`（每次真 Codex 嘗試一筆 `llm_records`）、額度檔 `llm-quota.json`。
- 不讀 `.env`、不寫 production DB：`build` 用 `mode=ro` 開快照與 production DB，其餘步驟只碰 `data/work/exp2/`。
- 不加 `--live` 的 `draft`／`run` 只重播帳本，缺錄音就停，不會呼叫 Codex。
- `--max-calls`（預設 25）是這一次執行最多幾次新的 Codex 嘗試。線上每天約用 33 次、全部用途合計上限 60，
  所以一天大約只剩 27 次給實驗；不夠就隔天再跑同一個指令接著做。
- `--per-source`：(c) 組用逐來源 KEEP／REMOVE（`FACT_CHECKER_PER_SOURCE`）。預設關，與試刊相同。
- `ablation`／`ablation-report --event-classes`：改成 (c4)＝(c) 打開 `FACT_CHECKER_EVENT_CLASSES`（事件四分類），
  結果寫 `results_c4.json`，不覆蓋 (c+)。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import asdict
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

WORK = ROOT / "data" / "work" / "exp2"
CASES, V1 = WORK / "cases.json", WORK / "v1.json"
LEDGER, QUOTA = WORK / "ledger.db", WORK / "llm-quota.json"
EXP1 = ROOT / "annotation" / "exp1"


def _set_work(path: Path) -> None:
    global WORK, CASES, V1, LEDGER, QUOTA
    WORK = path.expanduser().resolve()
    CASES, V1 = WORK / "cases.json", WORK / "v1.json"
    LEDGER, QUOTA = WORK / "ledger.db", WORK / "llm-quota.json"


def _configure(max_calls: int) -> None:
    """要在讀 settings／建立 CodexClient 之前。不載入 .env，DATABASE_URL 指到工作目錄，碰不到 production。"""
    WORK.mkdir(parents=True, exist_ok=True)
    os.environ["REDDIT_TRACKER_NO_DOTENV"] = "1"
    os.environ["DATABASE_URL"] = f"sqlite:///{WORK / 'scratch.db'}"
    os.environ["LLM_QUOTA_STATE_PATH"] = str(QUOTA)
    os.environ["LLM_DAILY_LIMIT"] = str(max_calls)
    from reddit_tracker.config import get_settings

    get_settings.cache_clear()
    settings = get_settings()
    if settings.database_url != f"sqlite:///{WORK / 'scratch.db'}" or Path(settings.llm_quota_state_path) != QUOTA:
        raise SystemExit(f"設定沒有指到 {WORK}，停止")


def _readonly_session(path: Path):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    if not path.is_file():
        raise SystemExit(f"找不到 {path}")
    return Session(create_engine(f"sqlite:///file:{path.resolve()}?mode=ro&uri=true", future=True))


class _Tracked:
    """記下沒成功的呼叫數（`misses`），讓 exp2 可以整組作廢而不是默默用模板稿。"""

    def __init__(self, inner) -> None:
        self.inner = inner
        self.misses = 0
        if hasattr(inner, "logs_attempts"):
            self.logs_attempts = inner.logs_attempts

    def __getattr__(self, name):
        return getattr(self.inner, name)

    def complete(self, **kwargs):
        try:
            return self.inner.complete(**kwargs)
        except Exception:
            self.misses += 1
            raise


class _LedgerReplay:
    """只重播帳本裡成功的回應；沒有就丟 ReplayMissing。"""

    def __init__(self, model: str) -> None:
        self.model = model

    def complete(self, **kwargs):
        from reddit_tracker.llm.records import lookup_ok
        from reddit_tracker.llm.replay import ReplayMissing, ReplayResult, prompt_text, request_hash

        key = request_hash(system=kwargs["system"], prompt=prompt_text(kwargs["messages"]),
                           model=self.model, schema=kwargs.get("json_schema"))
        cached = lookup_ok([LEDGER], key)
        if cached is None:
            raise ReplayMissing(f"帳本沒有這次請求的錄音（{key[:12]}）；加 --live 才會呼叫 Codex")
        return ReplayResult(cached)


def _client(live: bool, max_calls: int):
    from reddit_tracker.config import get_settings
    from reddit_tracker.eval.exp2 import DAY

    if not live:
        return _Tracked(_LedgerReplay(get_settings().codex_model))
    from reddit_tracker.llm.codex import CodexClient
    from reddit_tracker.llm.records import RecordingCodexClient, attempts_used, cli_version

    codex = CodexClient(max_retries=0, purpose="daily")
    return _Tracked(RecordingCodexClient(
        codex, db_path=LEDGER, version=cli_version(codex.binary), role="exp2", run_variant="mas",
        edition_date=DAY, max_attempts=attempts_used([LEDGER]) + max_calls,
    ))


def _ids(text: str) -> list[int]:
    path = Path(text)
    raw = path.read_text(encoding="utf-8") if path.is_file() else text
    return [int(part) for part in raw.replace("\n", ",").split(",") if part.strip()]


def cmd_build(args) -> int:
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    from reddit_tracker.config import get_settings
    from reddit_tracker.eval import exp1_results, exp2
    from reddit_tracker.models import Base
    from reddit_tracker.seeds.news_sources import load_registry
    from tests.regression import rebuild

    if CASES.exists() and not args.force:
        raise SystemExit(f"{CASES} 已存在。案例凍結後不該再動；真的要重建請加 --force（v1 與結果也要重跑）")
    registry = load_registry(get_settings().news_sources_path)
    names = {source.id: source.name for source in registry.sources}

    engine = create_engine("sqlite://", future=True)
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add_all(rebuild._source_item(item) for item in rebuild.load_items()["items"])
        session.flush()
        dev = exp2.dev_cases(
            session, [c for c in rebuild.load_cases() if c["case_id"] in {"E01", "E02", "E03", "E04", "E05"}],
            names, norm=rebuild.norm_title,
        )

    key_rows = exp1_results.read_csv(args.exp1_key)
    pairs = exp1_results.build_pairs(
        key_rows, exp1_results.read_csv(args.exp1_a), exp1_results.read_csv(args.exp1_b),
        exp1_results.read_csv(args.exp1_final) if args.exp1_final else None,
    )
    with _readonly_session(Path(args.exp1_db)) as session:
        holdout = exp2.holdout_cases(session, pairs, key_rows, names)

    normal = []
    if args.normal_ids:
        story_ids = _ids(args.normal_ids)
        if len(story_ids) != exp2.NORMAL_COUNT and not args.force:
            raise SystemExit(f"正常稿要 {exp2.NORMAL_COUNT} 篇，收到 {len(story_ids)} 篇（確定要這樣請加 --force）")
        with _readonly_session(Path(args.prod_db)) as session:
            if args.sample_dates:
                from reddit_tracker.daily.blind import EXP2_SEED, sample_exp2

                days = [date.fromisoformat(part) for part in args.sample_dates.split(",") if part.strip()]
                seed = EXP2_SEED if args.sample_seed is None else args.sample_seed
                exp2.check_normal_pick(story_ids, sample_exp2(session, days, seed=seed))
            else:
                print("⚠️ 沒給 --sample-dates：不檢查正常稿是否來自 sample_exp2 的候選清單。", file=sys.stderr)
            normal = exp2.normal_cases(session, story_ids, registry)
    else:
        print("⚠️ 沒給 --normal-ids：這份案例沒有正常稿，只能用來試跑。A 選完 15 篇後用 --force 重建。", file=sys.stderr)

    cases = [*dev, *holdout, *normal]
    exp2.save_cases(cases, CASES)
    print(f"寫入 {CASES}：開發集 {len(dev)}、保留集 {len(holdout)}、正常稿 {len(normal)}")
    for case in cases:
        print(f"  {case.case_id:10s} {case.group:8s} 來源 {len(case.evidence)}（無關 {len(case.wrong_item_ids)}） {case.note[:40]}")
    return 0


def cmd_draft(args) -> int:
    from reddit_tracker.eval import exp2

    cases = exp2.load_cases(CASES)
    drafts = exp2.draft_all(cases, _client(args.live, args.max_calls), WORK / "draft.db", V1)
    print(f"v1 共 {len(drafts)}/{len(cases)} 篇，存在 {V1}")
    return 0


def cmd_run(args) -> int:
    from reddit_tracker.eval import exp2

    cases = exp2.load_cases(CASES)
    drafts = json.loads(V1.read_text(encoding="utf-8")) if V1.is_file() else {}
    for arm in (list(exp2.ARMS) if args.arm == "all" else [args.arm]):
        outcomes = exp2.run_arm(arm, cases, drafts, _client(args.live, args.max_calls), WORK / f"arm_{arm}.db",
                                per_source=args.per_source)
        payload = {"arm": arm, "per_source": args.per_source, "outcomes": [asdict(o) for o in outcomes]}
        (WORK / f"results_{arm}.json").write_text(json.dumps(payload, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        print(f"{exp2.ARM_NAMES[arm]}：{exp2.summarize(outcomes)}")
    return 0


def cmd_ablation(args) -> int:
    from reddit_tracker.eval import exp2

    cases = exp2.select_cases(exp2.load_cases(CASES), [part.strip() for part in args.cases.split(",") if part.strip()])
    drafts = json.loads(V1.read_text(encoding="utf-8"))
    tag = "c4" if args.event_classes else "c_plus"
    outcomes, verdicts = exp2.run_ablation(cases, drafts, _client(args.live, args.max_calls), WORK / f"arm_{tag}.db",
                                           event_classes=args.event_classes)
    arm = exp2.EVENT_CLASS_ARM if args.event_classes else exp2.ABLATION_ARM
    payload = {
        "arm": arm, "per_source": not args.event_classes, "event_classes": args.event_classes,
        "case_ids": [case.case_id for case in cases],
        "outcomes": [asdict(o) for o in outcomes],
        "verdicts": verdicts,
    }
    (WORK / f"results_{tag}.json").write_text(json.dumps(payload, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"({arm})：{exp2.summarize(outcomes)}；刪除 {exp2.removal_counts(outcomes, cases)}")
    return 0


def cmd_ablation_report(args) -> int:
    from reddit_tracker.eval import exp2

    base = json.loads((WORK / "results_c.json").read_text(encoding="utf-8"))
    tag = "c4" if args.event_classes else "c_plus"
    plus = json.loads((WORK / f"results_{tag}.json").read_text(encoding="utf-8"))
    if base["per_source"]:
        raise SystemExit("results_c.json 已經開了逐來源判斷，不能當 (c) 的對照")
    print(exp2.render_ablation(
        [exp2.Outcome(**row) for row in base["outcomes"]], [exp2.Outcome(**row) for row in plus["outcomes"]],
        exp2.load_cases(CASES), plus["verdicts"],
        label="(c4) 事件四分類" if args.event_classes else "(c+) 逐來源判斷",
    ))
    return 0


def cmd_report(args) -> int:
    from reddit_tracker.config import get_settings
    from reddit_tracker.eval import exp2

    cases = exp2.load_cases(CASES)
    results, per_source = {}, False
    for arm in exp2.ARMS:
        path = WORK / f"results_{arm}.json"
        if path.is_file():
            payload = json.loads(path.read_text(encoding="utf-8"))
            results[arm] = [exp2.Outcome(**row) for row in payload["outcomes"]]
            per_source = per_source or (arm == "c" and payload["per_source"])
    drafts = json.loads(V1.read_text(encoding="utf-8")) if V1.is_file() else {}
    report = exp2.render_report(
        results, cases, generated=datetime.now(ZoneInfo("Asia/Taipei")).strftime("%Y-%m-%d %H:%M 台北"),
        model_version=get_settings().daily_model_version, per_source=per_source, v1_calls=len(drafts),
        labels_note=args.labels_note,
    )
    if not args.write:
        print(report)
        return 0
    out = ROOT / "docs" / "eval" / "exp2_results.md"
    report = exp2.keep_manual(report, out.read_text(encoding="utf-8") if out.is_file() else None)
    out.write_text(report, encoding="utf-8")
    print(f"寫入 {out}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    build = sub.add_parser("build")
    build.add_argument("--exp1-a", default=str(EXP1 / "exp1_A_100.csv"))
    build.add_argument("--exp1-b", default=str(EXP1 / "exp1_B_30.csv"))
    build.add_argument("--exp1-final", default=str(EXP1 / "exp1_resolution_disagreements.csv"))
    build.add_argument("--exp1-key", default=str(EXP1 / "_private" / "exp1_key.csv"))
    build.add_argument("--exp1-db", default=str(ROOT / "data" / "snapshots" / "2026-11-05.db"))
    build.add_argument("--prod-db", default=str(ROOT / "reddit_tracker.db"))
    build.add_argument("--normal-ids", help="A 選的正常稿 story id（逗號分隔，或一個檔案路徑）")
    build.add_argument("--sample-dates", help="給 A 的候選清單用的日期（同 sample_exp2.py --dates）；給了就檢查 A 的選稿都在清單裡")
    build.add_argument("--sample-seed", type=int, default=None, help="同 sample_exp2.py --seed（預設 EXP2_SEED）")
    build.add_argument("--force", action="store_true")
    build.set_defaults(func=cmd_build)

    for name, func in (("draft", cmd_draft), ("run", cmd_run)):
        step = sub.add_parser(name)
        step.add_argument("--live", action="store_true", help="呼叫真 Codex；不加只重播帳本")
        step.add_argument("--max-calls", type=int, default=25)
        step.set_defaults(func=func)
        if name == "run":
            step.add_argument("--arm", choices=["a", "b", "c", "all"], required=True)
            step.add_argument("--per-source", action="store_true")

    report = sub.add_parser("report")
    report.add_argument("--write", action="store_true")
    report.add_argument("--labels-note", default="保留集用實驗一的最終標註產生。")
    report.set_defaults(func=cmd_report)

    ablation = sub.add_parser("ablation")
    ablation.add_argument("--cases", required=True, help="案例編號，逗號分隔")
    ablation.add_argument("--live", action="store_true", help="呼叫真 Codex；不加只重播帳本")
    ablation.add_argument("--max-calls", type=int, default=25)
    ablation.set_defaults(func=cmd_ablation)
    ablation_report = sub.add_parser("ablation-report")
    ablation_report.set_defaults(func=cmd_ablation_report)
    for step in (ablation, ablation_report):
        step.add_argument("--event-classes", action="store_true",
                          help="改跑／改印 (c4)：FACT_CHECKER_EVENT_CLASSES 事件四分類（results_c4.json）")
    for name, step in sub.choices.items():
        step.add_argument("--work-dir", type=Path, required=name.startswith("ablation"),
                          help="工作目錄（預設 data/work/exp2）")

    args = parser.parse_args(argv)
    if args.work_dir:
        _set_work(args.work_dir)
    _configure(getattr(args, "max_calls", 25))
    from reddit_tracker.eval.exp2 import Exp2Error

    try:
        return args.func(args)
    except Exp2Error as exc:
        print(f"停止：{exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

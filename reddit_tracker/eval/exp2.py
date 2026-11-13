"""實驗二：查核員開與關（手冊 8.2）。

三組共用同一批案例與同一批記者 v1，只差查核員開關（`review_one(checker_mode=...)`）：

- (a) `off`：查核員全關（數字檢查照開）
- (b) `program`：只開程式工具（共同實體相關性規則）
- (c) `full`：程式工具＋查核員 LLM

案例三種：
- `dev`：E01–E05，把案例檔點名的無關素材加回證據包（查核工具照這 5 個案例設計，另列、不當主要成績）
- `holdout`：實驗一 test 裡「最終答案＝不是、方法 A 卻合併」的配對，把其中一則加進另一則所屬事件的證據包
- `normal`：標註員 A 從 25 篇候選挑出的 15 篇正常稿，證據包用當期快照凍結的素材

判定（程式判，不靠人看）：
- 擋下（dev／holdout）＝最終版不再引用無關來源，或稿件 HOLD
- 誤擋（normal）＝稿件 HOLD，或有來源被刪掉

這個模組不決定用哪個 client、不讀設定；腳本 `scripts/run_exp2.py` 負責路徑、額度與真 Codex。
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from ..daily.evidence import EvidenceItem, build_evidence_from_ids, raw_evidence_item
from ..daily.mas.orchestrator import (
    CHECKER_PER_SOURCE_SCHEMA, CHECKER_SCHEMA, _draft_from_template, registry_domains, reporter_draft, review_one,
)
from ..daily.store import add_story, latest_version
from ..models import Base, DailySnapshot, SourceItem, Story

DAY = date(2026, 11, 17)
NOW = datetime(2026, 11, 17, 2, 0, tzinfo=timezone.utc)
ARMS = {"a": "off", "b": "program", "c": "full"}
ARM_NAMES = {"a": "(a) 全關", "b": "(b) 只開程式工具", "c": "(c) 程式＋LLM"}
GROUPS = ("dev", "holdout", "normal")
MAX_HOLDOUT = 10
NORMAL_COUNT = 15


class Exp2Error(RuntimeError):
    pass


@dataclass
class Case:
    case_id: str
    group: str  # dev／holdout／normal
    section: str
    kind: str
    evidence: list[dict]  # EvidenceItem 的欄位
    wrong_item_ids: list[int] = field(default_factory=list)
    note: str = ""

    def items(self) -> list[EvidenceItem]:
        return [EvidenceItem(**row) for row in self.evidence]


@dataclass
class Outcome:
    case_id: str
    group: str
    arm: str
    status: str
    versions: int
    hold: bool
    removed_item_ids: list[int]
    blocked: bool | None  # dev／holdout：擋下了沒
    false_block: bool | None  # normal：誤擋了沒
    llm_calls: int
    checker_calls: int


# ── 案例 ──────────────────────────────────────────────────────────────────


def _kind(evidence: list[EvidenceItem]) -> str:
    return "report" if len({item.outlet for item in evidence}) >= 2 else "single_source"


def _case(case_id: str, group: str, section: str, evidence: list[EvidenceItem], wrong: list[int], note: str) -> Case:
    return Case(case_id, group, section, _kind(evidence), [asdict(item) for item in evidence], wrong, note)


def dev_cases(session: Session, cases: list[dict], source_names: dict[str, str], norm=lambda text: text) -> list[Case]:
    """E01–E05：`event_titles` 是事件本身的素材，`must_not_contain_titles` 是當時混進去的無關素材。

    `session` 裡要有 10/27 的素材（腳本用回歸 fixture 灌進暫存 DB）。同標題有多篇時取 id 最小的一篇。
    """
    rows = session.scalars(select(SourceItem).order_by(SourceItem.id)).all()
    by_title: dict[str, SourceItem] = {}
    for row in rows:
        by_title.setdefault(norm(row.title), row)
    out = []
    for case in cases:
        missing = [t for t in [*case["event_titles"], *case["must_not_contain_titles"]] if norm(t) not in by_title]
        if missing:
            raise Exp2Error(f"{case['case_id']} 的標題在素材裡找不到：{missing}")
        right = [by_title[norm(t)] for t in case["event_titles"]]
        wrong = [by_title[norm(t)] for t in case["must_not_contain_titles"]]
        evidence = [raw_evidence_item(m, source_names) for m in [*right, *wrong]]
        out.append(_case(case["case_id"], "dev", right[0].section, evidence, [m.id for m in wrong], case["error"]))
    return out


def holdout_pairs(pairs) -> list:
    """實驗一 test 裡最終答案「不是」、方法 A 卻合併的配對（`exp1_results.Pair`），依 pair_id 排序取前 10。"""
    picked = [p for p in pairs if p.split == "test" and p.final == "不是" and p.a_merged]
    return sorted(picked, key=lambda p: p.pair_id)[:MAX_HOLDOUT]


def holdout_cases(session: Session, pairs, key_rows: list[dict], source_names: dict[str, str]) -> list[Case]:
    """把配對的第 1 則（錯的）加進第 2 則所屬事件的證據包。`session` 是實驗一抽樣用的唯讀快照。"""
    keys = {row["pair_id"]: row for row in key_rows}
    out = []
    for pair in holdout_pairs(pairs):
        wrong_id, anchor_id = int(keys[pair.pair_id]["item_1"]), int(keys[pair.pair_id]["item_2"])
        anchor, wrong = session.get(SourceItem, anchor_id), session.get(SourceItem, wrong_id)
        if anchor is None or wrong is None:
            raise Exp2Error(f"{pair.pair_id} 的素材不在快照裡：{anchor_id}、{wrong_id}")
        member_ids = [anchor_id]
        if anchor.cluster_id is not None:
            member_ids = list(session.scalars(
                select(SourceItem.id).where(SourceItem.cluster_id == anchor.cluster_id, SourceItem.id != wrong_id)
            ).all())
        evidence = build_evidence_from_ids(session, member_ids, source_names, anchor_item_id=anchor_id).items
        evidence = [item for item in evidence if item.item_id != wrong_id]
        # 代表稿放 S1：查核員的程式工具拿 S1 當基準
        evidence.sort(key=lambda item: item.item_id != anchor_id)
        if not evidence or evidence[0].item_id != anchor_id:
            evidence.insert(0, raw_evidence_item(anchor, source_names))
        evidence.append(raw_evidence_item(wrong, source_names))
        out.append(_case(f"H-{pair.pair_id}", "holdout", anchor.section, evidence, [wrong_id],
                         f"實驗一 {pair.pair_id}：{pair.kind}／{pair.stratum}，方法 A 合併、最終答案不是"))
    return out


def normal_cases(session: Session, story_ids: list[int], registry) -> list[Case]:
    """A 選的正常稿：證據包照 `run_mas` 的做法，從當期快照凍結的素材 id 組。`session` 是 production 的唯讀複本。"""
    names = {source.id: source.name for source in registry.sources}
    domains = registry_domains(registry)
    out = []
    for story_id in story_ids:
        story = session.get(Story, story_id)
        if story is None or story.run_variant != "mas":
            raise Exp2Error(f"找不到 M 組稿 {story_id}")
        snapshot = session.scalar(select(DailySnapshot).where(DailySnapshot.edition_date == story.edition_date))
        raw = next((c for c in (snapshot.candidates if snapshot else []) if c["keeper_cluster_id"] == story.keeper_cluster_id), None)
        if raw is None:
            raise Exp2Error(f"稿 {story_id} 在 {story.edition_date} 的快照裡找不到")
        evidence = build_evidence_from_ids(
            session, list(raw.get("evidence_item_ids") or []), names,
            anchor_item_id=raw.get("anchor_item_id"), allowed_domains=domains,
        ).items
        if not evidence:
            raise Exp2Error(f"稿 {story_id} 的證據包是空的")
        out.append(_case(f"N-{story_id}", "normal", story.section, evidence, [], f"{story.edition_date} M 組稿 {story_id}"))
    return out


def save_cases(cases: list[Case], path: Path) -> None:
    ids = [case.case_id for case in cases]
    if len(ids) != len(set(ids)):
        raise Exp2Error("案例編號重複")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps([asdict(case) for case in cases], ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def load_cases(path: Path) -> list[Case]:
    return [Case(**row) for row in json.loads(path.read_text(encoding="utf-8"))]


# ── 執行 ──────────────────────────────────────────────────────────────────


class CountingClient:
    """包一層數呼叫次數（重播的也算一次：算的是這一組「需要」幾次模型呼叫）。"""

    def __init__(self, inner) -> None:
        self.inner = inner
        self.calls = 0
        self.checker_calls = 0
        if hasattr(inner, "logs_attempts"):
            self.logs_attempts = inner.logs_attempts

    def __getattr__(self, name):
        return getattr(self.inner, name)

    def complete(self, **kwargs):
        self.calls += 1
        if kwargs.get("json_schema") in (CHECKER_SCHEMA, CHECKER_PER_SOURCE_SCHEMA):
            self.checker_calls += 1
        return self.inner.complete(**kwargs)


def _failed(client) -> bool:
    """client 有 `misses`（沒成功的呼叫數）就看它；角色呼叫失敗時編排器會默默降級，實驗不能接受。"""
    return bool(getattr(client, "misses", 0))


def _engine(db_path: Path):
    db_path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(f"sqlite:///{db_path}", future=True)
    Base.metadata.create_all(engine)
    return engine


def _story(session: Session, index: int, case: Case) -> Story:
    return add_story(session, edition_date=DAY, run_variant="mas",
                     spec={"keeper_cluster_id": index, "section": case.section, "kind": case.kind})


def draft_all(cases: list[Case], client, db_path: Path, out_path: Path) -> dict[str, dict]:
    """記者 v1 只產生一次並存檔；已經有的案例不重寫。模型沒給可用的稿就停（不拿模板稿當 v1）。"""
    drafts = json.loads(out_path.read_text(encoding="utf-8")) if out_path.is_file() else {}
    if db_path.exists():
        db_path.unlink()
    engine = _engine(db_path)
    try:
        for index, case in enumerate(cases, start=1):
            if case.case_id in drafts:
                continue
            counter, degraded = CountingClient(client), []
            with Session(engine) as session:
                story = _story(session, index, case)
                headline, deck, body, why = reporter_draft(
                    session, counter, edition_date=DAY, story=story, evidence=case.items(), degraded=degraded,
                )
                session.commit()
            template = _draft_from_template(case.items(), case.kind)
            if degraded or _failed(client) or counter.calls == 0 or (headline, deck, body, why) == template:
                raise Exp2Error(f"{case.case_id} 的 v1 不是模型寫的（額度用完、呼叫失敗或回應不可用）；處理後重跑 draft")
            drafts[case.case_id] = {"headline": headline, "deck": deck, "body": body, "why_it_matters": why}
            out_path.write_text(json.dumps(drafts, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    finally:
        engine.dispose()
    return drafts


def run_arm(arm: str, cases: list[Case], drafts: dict[str, dict], client, db_path: Path, *, per_source: bool = False) -> list[Outcome]:
    """跑一組。每次都從空的 DB 開始；模型回應由 client 的帳本重播，不會重複花額度。"""
    missing = [case.case_id for case in cases if case.case_id not in drafts]
    if missing:
        raise Exp2Error(f"這些案例還沒有 v1，先跑 draft：{missing}")
    if db_path.exists():
        db_path.unlink()
    engine = _engine(db_path)
    outcomes = []
    try:
        for index, case in enumerate(cases, start=1):
            evidence = case.items()
            original = [item.item_id for item in evidence]
            saved = drafts[case.case_id]
            counter, degraded = CountingClient(client), []
            with Session(engine) as session:
                story = _story(session, index, case)
                review_one(
                    session, edition_date=DAY, story=story, evidence=evidence, client=counter, now=NOW,
                    degraded=degraded, per_source=per_source, checker_mode=ARMS[arm],
                    draft=(saved["headline"], saved["deck"], saved["body"], saved["why_it_matters"]),
                )
                final = latest_version(session, story.id)
                session.commit()
                status, versions, kept = final.status, final.version, set(final.source_ids or [])
            if degraded or _failed(client):
                raise Exp2Error(
                    f"{ARM_NAMES[arm]} 跑到 {case.case_id} 時有模型呼叫沒成功（額度用完、失敗或沒有錄音；degraded={degraded}），"
                    "這一組不算；處理後重跑（已成功的呼叫會從帳本重播，不重複花額度）"
                )
            removed = [item_id for item_id in original if item_id not in kept]
            hold = status == "hold"
            is_error = case.group != "normal"
            outcomes.append(Outcome(
                case_id=case.case_id, group=case.group, arm=arm, status=status, versions=versions, hold=hold,
                removed_item_ids=removed,
                blocked=(hold or not (set(case.wrong_item_ids) & kept)) if is_error else None,
                false_block=(hold or bool(removed)) if not is_error else None,
                llm_calls=counter.calls, checker_calls=counter.checker_calls,
            ))
    finally:
        engine.dispose()
    return outcomes


# ── 報告 ──────────────────────────────────────────────────────────────────


def summarize(outcomes: list[Outcome]) -> dict:
    def count(group, attr):
        rows = [o for o in outcomes if o.group == group]
        return sum(bool(getattr(o, attr)) for o in rows), len(rows)

    return {
        "dev": count("dev", "blocked"), "holdout": count("holdout", "blocked"), "normal": count("normal", "false_block"),
        "llm_calls": sum(o.llm_calls for o in outcomes), "checker_calls": sum(o.checker_calls for o in outcomes),
    }


def render_report(results: dict[str, list[Outcome]], cases: list[Case], *, generated: str, model_version: str,
                  per_source: bool, v1_calls: int, labels_note: str) -> str:
    sizes = {group: sum(case.group == group for case in cases) for group in GROUPS}
    out = [
        "# 實驗二結果：查核員開與關",
        "",
        f"- 產生時間：{generated}；腳本 `scripts/run_exp2.py`",
        f"- 模型：`{model_version}`；`FACT_CHECKER_PER_SOURCE`＝{'開' if per_source else '關'}（只影響 (c) 組）",
        f"- 案例：開發集 {sizes['dev']}（E01–E05）、保留集 {sizes['holdout']}、正常稿 {sizes['normal']}。{labels_note}",
        f"- 記者 v1 只產生一次（{v1_calls} 篇，各 1 次模型呼叫），三組共用；下表的 LLM 呼叫數不含這 {v1_calls} 次。",
        "- 擋下＝最終版不再引用無關來源，或稿件 HOLD。誤擋＝正常稿 HOLD，或有來源被刪掉。",
        "- 只能說「在這些案例上」；結論以保留集為主，開發集是查核工具設計時就看過的案例。",
        "",
        "| 設定 | 開發集擋下 | 保留集擋下 | 正常稿誤擋 | LLM 呼叫數（其中查核員） |",
        "| --- | --- | --- | --- | --- |",
    ]
    for arm in ARMS:
        if arm not in results:
            out.append(f"| {ARM_NAMES[arm]} | 還沒跑 | | | |")
            continue
        s = summarize(results[arm])
        out.append(
            f"| {ARM_NAMES[arm]} | {s['dev'][0]}/{s['dev'][1]} | {s['holdout'][0]}/{s['holdout'][1]} "
            f"| {s['normal'][0]}/{s['normal'][1]} | {s['llm_calls']}（{s['checker_calls']}） |"
        )
    if sizes["holdout"] < MAX_HOLDOUT:
        out += ["", f"保留集只有 {sizes['holdout']} 篇（上限 {MAX_HOLDOUT}）：實驗一 test 裡符合條件的配對就這麼多，照實報。"]
    if sizes["normal"] != NORMAL_COUNT:
        out += ["", f"⚠️ 正常稿是 {sizes['normal']} 篇，不是手冊要求的 {NORMAL_COUNT} 篇。"]
    out += ["", "## 逐案結果", "", "每格：最終狀態／版本數／被刪的來源數；✅＝擋下，❌＝沒擋，⚠️＝誤擋。", "",
            "| 案例 | 類別 | " + " | ".join(ARM_NAMES[a] for a in ARMS) + " | 說明 |", "| --- | --- | --- | --- | --- | --- |"]
    by_key = {(o.case_id, arm): o for arm, rows in results.items() for o in rows}
    for case in cases:
        cells = []
        for arm in ARMS:
            o = by_key.get((case.case_id, arm))
            if o is None:
                cells.append("—")
                continue
            mark = ("✅" if o.blocked else "❌") if case.group != "normal" else ("⚠️" if o.false_block else "")
            cells.append(f"{mark} {o.status}／v{o.versions}／刪 {len(o.removed_item_ids)}".strip())
        out.append(f"| {case.case_id} | {case.group} | " + " | ".join(cells) + f" | {case.note[:50]} |")
    return "\n".join(out) + "\n"

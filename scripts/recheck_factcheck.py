"""重跑查核員的程式相關性檢查（不呼叫 LLM），對照 M 組當期實際刪掉的來源。

用 DB 複本（唯讀開啟）裡某幾期 M 組稿件的第 1 版來源（`story_versions.source_ids` 的順序就是 S1、S2…），
逐一列出每個（稿件, 來源）：

- 舊程式：修正前 `irrelevant_sources`（標題共同名字、不看句首字佐證）是否點名；
- 當期實際：`agent_messages` 的 IRRELEVANT_SOURCE CHALLENGE 有沒有刪它（`drop_sids`）；
- 新程式：現在的 `irrelevant_sources` 是否點名；
- 查核員：當期存下的 `llm_assessment` 是否判定同一事件（`checker_says_same_event`）；
- 新決定：點名且查核員沒有判定同一事件才刪（`_check_and_maybe_revise` 的規則）。

    uv run python scripts/recheck_factcheck.py --db 複本.db --dates 2026-10-31,2026-11-01
    uv run python scripts/recheck_factcheck.py --db 複本.db --dates 2026-10-31,2026-11-01 \
        --export-fixture tests/regression/fixtures/factcheck_1031_1101.json

`--export-fixture` 只匯出有 IRRELEVANT_SOURCE CHALLENGE 的稿（標題、摘要、第 1／2 版稿、查核員回應），給回歸測試用。
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import zhconv  # noqa: E402
from sqlalchemy import create_engine, select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from reddit_tracker.collection.entities import load_lexicon  # noqa: E402
from reddit_tracker.daily.evidence import EVIDENCE_SUMMARY_CHARS, EvidenceItem  # noqa: E402
from reddit_tracker.daily.mas.orchestrator import checker_says_same_event, irrelevant_sources  # noqa: E402
from reddit_tracker.models import AgentMessage, SourceItem, Story, StoryVersion  # noqa: E402
from reddit_tracker.seeds.news_sources import load_registry  # noqa: E402


def legacy_irrelevant(evidence: list[EvidenceItem]) -> set[int]:
    """修正前（2026-11-01 以前）的規則：S1 與來源標題 `shared(..., None)`，句首字一律不算名字。"""
    if len(evidence) < 2:
        return set()
    lexicon = load_lexicon()
    anchor = lexicon.entities(evidence[0].title, (evidence[0].lang or "").startswith("zh"))
    bad = set()
    for index, item in enumerate(evidence[1:], start=2):
        if not lexicon.shared(anchor, lexicon.entities(item.title, (item.lang or "").startswith("zh")), None):
            bad.add(index)
    return bad


def _evidence_item(row: SourceItem, names: dict[str, str]) -> EvidenceItem:
    convert = (lambda text: zhconv.convert(text or "", "zh-tw")) if row.lang == "zh" else (lambda text: text or "")
    return EvidenceItem(
        outlet=row.source_id, source_id=row.source_id, source_name=names.get(row.source_id, row.source_id),
        tier=row.tier, lang=row.lang, title=convert(row.title), summary=convert(row.summary)[:EVIDENCE_SUMMARY_CHARS],
        url=row.url, published_at=row.published_at.isoformat(timespec="minutes"), item_id=row.id,
    )


def _version_dict(version: StoryVersion | None) -> dict | None:
    if version is None:
        return None
    return {
        "headline": version.headline, "deck": version.deck or "", "body": version.body,
        "why_it_matters": version.why_it_matters or "", "source_ids": list(version.source_ids or []),
    }


def load_records(session: Session, dates: list[date]) -> list[dict]:
    """每篇 M 組稿：第 1 版的證據（S 順序）與查核員的 CHALLENGE。"""
    names = {source.id: source.name for source in load_registry().sources}
    records = []
    stories = session.scalars(
        select(Story).where(Story.edition_date.in_(dates), Story.run_variant == "mas").order_by(Story.id)
    )
    for story in stories:
        versions = {
            v.version: v for v in session.scalars(select(StoryVersion).where(StoryVersion.story_id == story.id))
        }
        first = versions.get(1)
        if first is None:
            continue
        ids = list(first.source_ids or [])
        rows = {row.id: row for row in session.scalars(select(SourceItem).where(SourceItem.id.in_(ids)))}
        evidence = [_evidence_item(rows[i], names) for i in ids if i in rows]
        challenge = session.scalar(
            select(AgentMessage).where(
                AgentMessage.story_id == story.id, AgentMessage.sender_role == "fact_checker",
                AgentMessage.type == "CHALLENGE",
            ).order_by(AgentMessage.id)
        )
        payload = dict(challenge.payload or {}) if challenge is not None else {}
        records.append({
            "story_id": story.id,
            "edition_date": story.edition_date.isoformat(),
            "keeper_cluster_id": story.keeper_cluster_id,
            "section": story.section,
            "kind": story.kind,
            "evidence": [asdict(item) for item in evidence],
            "challenge": {
                "problem": payload.get("problem"),
                "drop_sids": list(payload.get("drop_sids") or []),
                "llm_assessment": payload.get("llm_assessment"),
            } if challenge is not None else None,
            "v1": _version_dict(first),
            "v2": _version_dict(versions.get(2)),
        })
    return records


def recheck(records: list[dict]) -> list[dict]:
    """逐（稿件, 來源）比對新舊決定。"""
    rows = []
    for record in records:
        evidence = [EvidenceItem(**item) for item in record["evidence"]]
        if len(evidence) < 2:
            continue
        challenge = record["challenge"] or {}
        stored_drop = set(challenge.get("drop_sids") or []) if challenge.get("problem") == "IRRELEVANT_SOURCE" else set()
        assessment = challenge.get("llm_assessment")
        legacy = legacy_irrelevant(evidence)
        flagged = {index for index, _ in irrelevant_sources(evidence)}
        same = checker_says_same_event(assessment)
        for index, item in enumerate(evidence, start=1):
            if index == 1:
                continue
            new_cut = index in flagged and not same
            rows.append({
                "story_id": record["story_id"], "edition_date": record["edition_date"], "sid": index,
                "item_id": item.item_id, "source": item.source_id, "title": item.title,
                "legacy_flag": index in legacy, "stored_cut": index in stored_drop, "new_flag": index in flagged,
                "llm": "none" if assessment is None else ("same" if same else "challenge"),
                "new_cut": new_cut,
            })
    return rows


def format_rows(rows: list[dict]) -> str:
    def mark(flag: bool) -> str:
        return "cut " if flag else "keep"

    lines = [
        "story  date        S   item   source              legacy  stored  new_flag  llm        new   title",
    ]
    changed = 0
    for row in rows:
        changed += row["stored_cut"] != row["new_cut"]
        lines.append(
            f"{row['story_id']:<6} {row['edition_date']} S{row['sid']:<2} {row['item_id']:<6} {row['source']:<19} "
            f"{'flag' if row['legacy_flag'] else '-':<7} {mark(row['stored_cut']):<7} {'flag' if row['new_flag'] else '-':<9} "
            f"{row['llm']:<10} {mark(row['new_cut'])}  {row['title'][:48]}"
        )
    stored = sum(r["stored_cut"] for r in rows)
    new = sum(r["new_cut"] for r in rows)
    lines += [
        "",
        f"來源共 {len(rows)} 個（不含 S1）；當期刪 {stored} 個，新規則刪 {new} 個，決定改變 {changed} 個。",
        "legacy＝修正前程式是否點名；stored＝當期實際刪除；new_flag＝現行程式是否點名；"
        "llm＝當期查核員回應（same＝判定同一事件，challenge＝有異議，none＝當期沒有呼叫）。",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--db", type=Path, required=True, help="DB 複本（唯讀開啟）")
    parser.add_argument("--dates", required=True, help="逗號分隔的出刊日 YYYY-MM-DD")
    parser.add_argument("--export-fixture", type=Path, help="把有 IRRELEVANT_SOURCE 的稿匯出成回歸 fixture")
    args = parser.parse_args(argv)
    dates = [date.fromisoformat(part) for part in args.dates.split(",") if part]
    engine = create_engine(f"sqlite:///file:{args.db.resolve()}?immutable=1&uri=true")
    with Session(engine) as session:
        records = load_records(session, dates)
    print(format_rows(recheck(records)))
    if args.export_fixture:
        wanted = [r for r in records if (r["challenge"] or {}).get("problem") == "IRRELEVANT_SOURCE"]
        args.export_fixture.write_text(json.dumps(wanted, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        print(f"\nfixture：{args.export_fixture}（{len(wanted)} 篇）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

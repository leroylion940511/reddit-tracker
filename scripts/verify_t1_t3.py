"""手冊 7.2／7.3：在 10/27 的 M 組複本上用真 Codex 跑 T1（E06 巴西兩版搶稿）與 T3（頭版提案 8 則）。

    uv run python scripts/verify_t1_t3.py [--live]

- 來源：`data/work/1027_mas_replay.db`（`verify_mas_merge.py --stage mas-replay` 的產物，已有 12 篇正式稿與 page_plans），
  複製成 `data/work/1027_t1t3.db` 再寫。
- 分版主編的 PITCH 由程式注入（現行分版主編只看本版，不會自然搶同一篇）；**總編 DECISION 由模型決定**，
  程式只驗證合不合規則（手冊 7.2「不合格：DECISION 是程式先排好」）。只呼叫總編，每個情境 1 次（失敗重試 1 次）。
- 每次 subprocess 嘗試都寫進複本 `llm_records`；額度用 `data/work/llm-quota-merge.json`、上限 40。
- 不加 `--live` 時只用錄音重播（`tests/regression/fixtures/1027_t1t3_records.json`），找不到就失敗。
"""

from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import sys
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "scripts")]

from verify_mas_merge import DAY, FIXTURES, NOW, WORK, ReplayThenCodex, configure  # noqa: E402

SOURCE = WORK / "1027_mas_replay.db"
TARGET = WORK / "1027_t1t3.db"
RECORDS = FIXTURES / "1027_t1t3_records.json"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--live", action="store_true")
    args = parser.parse_args()
    if not SOURCE.exists():
        raise SystemExit("先跑 scripts/verify_mas_merge.py --stage mas-replay")
    for suffix in ("", "-wal", "-shm"):
        Path(f"{TARGET}{suffix}").unlink(missing_ok=True)
    shutil.copyfile(SOURCE, TARGET)
    configure(TARGET)

    from sqlalchemy import select

    from reddit_tracker.daily.mas.orchestrator import (
        MasResult, Pitch, _conflicts, _resolve_t1, _resolve_t3, format_trace,
    )
    from reddit_tracker.daily.mas.protocol import Clock, post_message
    from reddit_tracker.db import session_scope
    from reddit_tracker.llm.records import bind_log_session, export_ok_records
    from reddit_tracker.models import AgentMessage, PagePlan, Story

    client = ReplayThenCodex(args.live)
    if RECORDS.exists():
        from reddit_tracker.llm.replay import load_records

        client.records.update(load_records(RECORDS))
    conn = sqlite3.connect(TARGET)
    baseline = conn.execute("select coalesce(max(id),0) from llm_records").fetchone()[0]
    conn.close()
    summary: dict = {}
    with session_scope() as session, bind_log_session(session):
        plan = session.scalar(select(PagePlan).where(PagePlan.edition_date == DAY, PagePlan.run_variant == "mas")
                              .order_by(PagePlan.plan_version.desc()))
        front = plan.slots["front"]
        front_ids = [front["lead"], *front["second"], *front["briefs"]]
        stories = {s.id: s for s in session.scalars(select(Story).where(
            Story.edition_date == DAY, Story.run_variant == "mas"))}
        base = []
        for section, slots in plan.slots["sections"].items():
            for slot in slots:
                sid = slot["story_id"]
                base.append(Pitch(section=section, story_id=sid, angle=stories[sid].section,
                                  priority="front" if sid in front_ids else "section"))
        brazil = next(p for p in base if p.section == "world" and p.story_id == front["lead"])
        clock = Clock(NOW)

        # T1：科技版主編也搶巴西大選（預測市場翻車的角度），兩個 PITCH 指向同一個 story_id
        rival = Pitch(section="tech", story_id=brazil.story_id, angle="預測市場翻車：押注 Bolsonaro 的市場全錯",
                      priority="front")
        t1_pitches = [brazil, rival]
        for p in t1_pitches:
            post_message(session, run_variant="mas", edition_date=DAY, sender="section_editor", recipient="eic",
                         type="PITCH", now=clock.tick(), story_id=p.story_id,
                         payload={"section": p.section, "angle": p.angle, "priority": p.priority, "scenario": "T1"})
        t1 = MasResult()
        _resolve_t1(session, edition_date=DAY, conflicts=_conflicts(t1_pitches), client=client, clock=clock,
                    hold_ids=set(), result=t1, pitches=base + [rival])
        summary["T1"] = {"page_plan_ids": t1.page_plan_ids, "rejected": t1.rejected_decision_ids}

        # T3：三位主編各再推 2–3 則上頭版，頭版提案 8 則 > 6 個位置
        extra = [p for p in base if p.priority == "section"][:2]
        t3_front = [p for p in base if p.priority == "front"] + [replace(p, priority="front") for p in extra]
        for p in extra:
            post_message(session, run_variant="mas", edition_date=DAY, sender="section_editor", recipient="eic",
                         type="PITCH", now=clock.tick(), story_id=p.story_id,
                         payload={"section": p.section, "angle": p.angle, "priority": "front", "scenario": "T3"})
        t3 = MasResult()
        _resolve_t3(session, edition_date=DAY, front=t3_front, client=client, clock=clock, hold_ids=set(), result=t3)
        summary["T3"] = {"front_pitches": len(t3_front), "page_plan_ids": t3.page_plan_ids,
                         "rejected": t3.rejected_decision_ids}
        decisions = session.scalars(select(AgentMessage).where(
            AgentMessage.edition_date == DAY, AgentMessage.type.in_(("DECISION", "PAGE_OBJECTION")),
            AgentMessage.id > 0).order_by(AgentMessage.id)).all()
        summary["messages"] = [
            {"id": m.id, "sender": m.sender_role, "type": m.type, "status": m.status,
             "payload": m.payload} for m in decisions[-4:]
        ]
        plans = session.scalars(select(PagePlan).where(PagePlan.edition_date == DAY, PagePlan.run_variant == "mas")
                                .order_by(PagePlan.plan_version)).all()
        summary["page_plans"] = [{"v": p.plan_version, "decided_by": p.decided_by_message_id,
                                  "front": p.slots.get("front")} for p in plans]
        (WORK / "merge-t1t3-trace.txt").write_text(format_trace(session, DAY, "mas", None), encoding="utf-8")
    conn = sqlite3.connect(TARGET)
    rows = conn.execute("select role, count(*), sum(ok) from llm_records where id>? and provider='codex' group by role",
                        (baseline,)).fetchall()
    conn.close()
    summary["attempts"] = client.attempts
    summary["reused"] = client.reused
    summary["llm_records"] = [list(r) for r in rows]
    assert sum(r[1] for r in rows) == client.attempts, (rows, client.attempts)
    print(json.dumps(summary, ensure_ascii=False, indent=1, default=str))
    (WORK / "merge-t1t3-summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1, default=str) + "\n")
    if args.live:
        export_ok_records([TARGET], RECORDS)
        conn = sqlite3.connect(TARGET)
        new = {r[0] for r in conn.execute("select request_hash from llm_records where id>?", (baseline,))}
        conn.close()
        rows = [r for r in json.loads(RECORDS.read_text(encoding="utf-8")) if r["request_hash"] in new]
        RECORDS.write_text(json.dumps(rows, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

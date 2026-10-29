"""10/27 integration evidence. --stage t2a|mas|mas-replay; --live explicitly allows bounded Codex.

mas-replay：在新的 data/work/1027_mas_replay.db 只用錄音重播整期 M 組（找不到錄音就失敗，不呼叫 Codex），
用來確認程式修改後 request_hash 沒變、回放頁仍可用。

Only copies in data/work are written. Regression must be recorded first using
LLM_QUOTA_STATE_PATH=data/work/llm-quota-merge.json LLM_DAILY_LIMIT=40.
No publication, network collection, or production access.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
import sys
from dataclasses import asdict
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
WORK = ROOT / "data/work"
DAY = date(2026, 10, 27)
NOW = datetime(2026, 10, 26, 22, tzinfo=timezone.utc)
FIXTURES = ROOT / "tests/regression/fixtures"


def configure(path):
    assert path.resolve().is_relative_to(WORK)
    os.environ.update(REDDIT_TRACKER_NO_DOTENV="1", DATABASE_URL=f"sqlite:///{path}",
                      LLM_QUOTA_STATE_PATH=str(WORK / "llm-quota-merge.json"), LLM_DAILY_LIMIT="40",
                      DAILY_MODE="mas", DAILY_SITE_DIR=str(WORK / "merge-site"))
    from reddit_tracker.config import get_settings
    get_settings.cache_clear()


def migrate(path):
    configure(path)
    from alembic import command
    from alembic.config import Config
    command.upgrade(Config(str(ROOT / "alembic.ini")), "head")


class ReplayThenCodex:
    logs_attempts = True

    def __init__(self, live):
        from reddit_tracker.llm.codex import CodexClient
        from reddit_tracker.llm.records import cli_version, model_version
        from reddit_tracker.llm.replay import load_records
        self.codex = CodexClient(max_retries=1)
        self.model = self.codex.model
        self.guard = self.codex.guard
        self.codex.model_version = model_version(self.codex, cli_version(self.codex.binary)) if live else self.model
        self.live = live
        self.attempts = 0
        self.reused = 0
        self.records = load_records(FIXTURES / "1027_llm_records.json")
        for name in ("1027_t2a_records.json", "1027_mas_records.json"):
            if (FIXTURES / name).exists():
                self.records.update(load_records(FIXTURES / name))
        self.requests = []
        original = self.codex._run_once

        def counted(prompt, schema):
            # The shared ModelQuotaGuard has already charged this subprocess attempt.
            total = sum(self.guard._load().get("models", {}).values())
            if total > 40:
                raise AssertionError("task quota exceeded")
            self.attempts += 1
            print(f"[live] attempt={self.attempts} quota={total}/40", flush=True)
            return original(prompt, schema)
        self.codex._run_once = counted

    def complete(self, **kwargs):
        from reddit_tracker.llm.replay import ReplayMissing, ReplayResult, request_hash, prompt_text
        key = request_hash(system=kwargs["system"], prompt=prompt_text(kwargs["messages"]),
                           model=self.model, schema=kwargs.get("json_schema"))
        self.requests.append({"request_hash": key, "system": kwargs["system"], "messages": kwargs["messages"],
                              "schema": kwargs.get("json_schema")})
        if key in self.records:
            self.reused += 1
            return ReplayResult(self.records[key])
        if not self.live:
            raise ReplayMissing(key)
        return self.codex.complete(**kwargs)


def t2a(path, client):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from reddit_tracker.daily.evidence import EvidenceItem, build_evidence_from_ids
    from reddit_tracker.daily.mas.orchestrator import review_one, format_trace
    from reddit_tracker.daily.store import add_story, upsert_snapshot, add_page_plan
    from reddit_tracker.llm.records import bind_log_session
    from reddit_tracker.models import SourceItem
    from reddit_tracker.seeds.news_sources import load_registry
    registry = load_registry()
    groups = json.loads((FIXTURES / "1027_groups.json").read_text())
    # Original pre-fix grouping plus the recorded cross-language merge [403,410].
    ids = list(dict.fromkeys(groups["410"] + groups["403"]))
    engine = create_engine(f"sqlite:///{path}")
    with Session(engine) as s:
        source_names = {r.id: r.name for r in registry.sources}
        pack = build_evidence_from_ids(s, ids, source_names)
        evidence = pack.items
        football = s.get(SourceItem, 1053)
        assert football is not None and football.id in ids
        # Intentionally retain E01 contamination for the second-line checker demo.
        evidence = [e for e in evidence if e.item_id != football.id]
        evidence.append(EvidenceItem(outlet="apnews.com", source_id=football.source_id, source_name="AP",
                                    tier=football.tier, lang=football.lang, title=football.title,
                                    summary=football.summary or "", url=football.url,
                                    published_at=football.published_at.isoformat(), item_id=football.id))
        spec = {"keeper_cluster_id": 410, "merged_cluster_ids": [403], "section": "world", "kind": "report",
                "score": 50, "evidence_item_ids": ids, "anchor_item_id": evidence[0].item_id}
        upsert_snapshot(s, DAY, [spec], NOW)
        story = add_story(s, edition_date=DAY, run_variant="mas", spec=spec)
        with bind_log_session(s):
            version = review_one(s, edition_date=DAY, story=story, evidence=evidence, client=client, now=NOW)
        add_page_plan(s, edition_date=DAY, run_variant="mas", now=NOW,
                      slots={"front": {"lead": story.id, "second": [], "briefs": []},
                             "sections": {"world": [{"story_id": story.id, "display": "link"}]}})
        trace = format_trace(s, DAY, "mas", 410)
        s.commit()  # Preserve every attempt even if acceptance below fails.
        (WORK / "merge-t2a-trace.txt").write_text(trace)
        assert version.version >= 2 and version.status == "checked", trace
        assert 1053 not in version.source_ids and "CHALLENGE" in trace and "REVISION_DONE" in trace
        (FIXTURES / "1027_t2a_evidence.json").write_text(json.dumps(
            {"spec": spec, "evidence": [asdict(e) for e in evidence]}, ensure_ascii=False, indent=1)+"\n")
    engine.dispose()


def mas(path, client):
    from reddit_tracker.daily import run
    from reddit_tracker.daily.writer import DailyWriter
    from reddit_tracker.db import session_scope
    from reddit_tracker.models import DailyEdition
    from sqlalchemy import select
    # Copy already has repaired clustering; do not run collection or recompute it.
    with session_scope() as s:
        old = s.scalar(select(DailyEdition).where(DailyEdition.edition_date == DAY))
        market = (old.stats or {}).get("market") if old else None
        if old:
            s.delete(old)
    run.fetch_market_box = lambda: market
    run.prepare_daily(DAY, now=NOW, mode="mas", writer=DailyWriter("codex", client=client), refresh=True)


def report(path, client, baseline, stage):
    from reddit_tracker.llm.records import export_ok_records
    from reddit_tracker.web import newsroom_page
    response = newsroom_page(DAY)
    assert response.status_code == 200
    html = response.body.decode()
    (WORK / f"merge-{stage}-newsroom.html").write_text(html)
    conn = sqlite3.connect(path)
    counts = dict(conn.execute("select role,count(*) from llm_records where id>? and provider='codex' group by role", (baseline,)))
    actual = sum(counts.values())
    assert actual == client.attempts, (actual, client.attempts)
    roles = dict(conn.execute("select sender_role,count(*) from agent_messages where edition_date='2026-10-27' group by sender_role"))
    for role in roles:
        assert role in html
    summary = {"stage": stage, "attempts": client.attempts, "reused": client.reused, "role_calls": counts,
               "message_roles": roles, "http_status": response.status_code,
               "tables": {table: conn.execute(f"select count(*) from {table}").fetchone()[0]
                          for table in ("stories", "story_versions", "agent_messages", "page_plans", "llm_records")},
               "model_version": client.codex.model_version}
    edition = conn.execute("select stats from daily_editions where edition_date='2026-10-27'").fetchone()
    if edition:
        summary["stats"] = json.loads(edition[0])
    conn.close()
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    (WORK / f"merge-{stage}-summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2)+"\n")
    if stage not in ("mas-replay", "mas-rerun"):
        export_ok_records([path], FIXTURES / f"1027_{stage}_records.json")
    (WORK / f"merge-{stage}-requests.json").write_text(json.dumps(client.requests, ensure_ascii=False, indent=1)+"\n")


def _merge_mas_fixture(path):
    """mas-rerun：程式改了之後補錄對不上的請求，併進 1027_mas_records.json（舊的 hash 保留）。"""
    from reddit_tracker.llm.records import export_ok_records

    tmp = WORK / "merge-mas-rerun-records.json"
    export_ok_records([path], tmp)
    target = FIXTURES / "1027_mas_records.json"
    rows = {r["request_hash"]: r for r in json.loads(target.read_text(encoding="utf-8"))}
    for row in json.loads(tmp.read_text(encoding="utf-8")):
        if row.get("run_variant") == "mas":
            rows.setdefault(row["request_hash"], row)
    ordered = sorted(rows.values(), key=lambda r: (r["called_at"] or "", r["request_hash"]))
    target.write_text(json.dumps(ordered, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", choices=("t2a", "mas", "mas-replay", "mas-rerun"), required=True)
    parser.add_argument("--live", action="store_true")
    args = parser.parse_args()
    path = WORK / {"t2a": "1027_e01.db", "mas": "1027_mas.db", "mas-replay": "1027_mas_replay.db",
                   "mas-rerun": "1027_mas_rerun.db"}[args.stage]
    if args.stage in ("mas-replay", "mas-rerun"):
        if args.live and args.stage == "mas-replay":
            raise SystemExit("mas-replay 只重播，不能加 --live")
        for suffix in ("", "-wal", "-shm"):
            Path(f"{path}{suffix}").unlink(missing_ok=True)
    elif path.exists():
        raise SystemExit(f"Refusing to overwrite existing evidence: {path}")
    source = ROOT / "data/snapshots/2026-10-27.db" if args.stage == "t2a" else WORK / "1027_rebuild.db"
    shutil.copyfile(source, path)
    path.chmod(0o644)
    migrate(path)
    conn = sqlite3.connect(path)
    baseline = conn.execute("select coalesce(max(id),0) from llm_records").fetchone()[0]
    conn.close()
    client = ReplayThenCodex(args.live)
    (t2a if args.stage == "t2a" else mas)(path, client)
    if args.stage == "mas-rerun":
        _merge_mas_fixture(path)
    if client.attempts or (args.stage == "mas-replay" and not client.reused):
        print(f"[verify] attempts={client.attempts} reused={client.reused}")
    report(path, client, baseline, args.stage)


if __name__ == "__main__":
    main()

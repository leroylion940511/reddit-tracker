"""E11（莫德納癌症疫苗）的離線重播。

回歸重編沒有把這則送進刊出的版面，所以 `cases/E11.json` 的條件在重編版是 skip。
要檢查標題，得把這一則單獨送進 M 組：記者寫稿、程式查核（可疑才叫查核員）、
文稿編輯看標題與正文。真 Codex 只在 `scripts/record_e11.py --live` 呼叫；
這裡與 pytest 只重播 fixture，找不到錄音就失敗，不改叫模型。

故事身份（2026-11-06 用 `1027_items.json.xz` 逐輪聚合核對過）：
錨點是 E11 `event_titles` 的 MarketWatch 稿（source_item 2736）。現行聚合後它自成一則、
單一來源、財經改判國際。刊出稿裡另一家 STAT「Five biotech updates」（item 3875，
摘要才有 “expected in 2027”）是另一個 cluster，不併回這包證據。
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict
from datetime import date, datetime, timezone
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from reddit_tracker.daily.evidence import EvidenceItem, build_evidence_from_ids
from reddit_tracker.daily.mas.orchestrator import _copy_edit_front, review_one
from reddit_tracker.daily.mas.protocol import Clock
from reddit_tracker.daily.scoring import ScoredCluster, kind_for
from reddit_tracker.daily.sections import rewrite_sections
from reddit_tracker.daily.store import add_page_plan, add_story, latest_version
from reddit_tracker.llm.replay import ReplayClient, load_records, request_hash
from reddit_tracker.models import Base, SourceItem, StoryCluster, StoryVersion
from reddit_tracker.seeds.news_sources import load_registry

from .rebuild import _insert_items, _utc, load_items, norm_title, recomputed_duplicates

FIXTURES = Path(__file__).parent / "fixtures"
CASES = Path(__file__).parent / "cases"
RECORDS_NAME = "1027_e11_records.json"
EVIDENCE_NAME = "1027_e11_evidence.json"
RECORDS = FIXTURES / RECORDS_NAME
EVIDENCE = FIXTURES / EVIDENCE_NAME
DAY = date(2026, 10, 27)
NOW = datetime(2026, 10, 26, 22, tzinfo=timezone.utc)
# 記者 1 次＋文稿編輯 1 次；草稿若帶上證據裡沒有的數字會再加查核與修稿。上限留 5。
MAX_ATTEMPTS = 5
LIVE_COMMAND = "uv run python scripts/record_e11.py --live"
CHECK_COMMAND = "uv run python scripts/record_e11.py --check"
# 10/27 刊出稿的第二個來源。只用來在說明裡標出它沒有被併進這則，選擇證據不靠這個 id。
STAT_TITLE = "STAT+: Five biotech updates to read after ESMO this weekend"


def load_case() -> dict:
    return json.loads((CASES / "E11.json").read_text(encoding="utf-8"))


def headline_violations(headline: str | None) -> list[str]:
    """與回歸條件 `headline_must_not_match` 同一套樣式。"""
    return [
        pattern
        for pattern in load_case()["headline_must_not_match"]
        if re.search(pattern, headline or "")
    ]


def missing_recording_message() -> str:
    return (
        "E11 還沒有真 Codex 錄音，離線重播不適用（不是通過）。"
        f"在 Mac 的專案根目錄跑 `{LIVE_COMMAND}`："
        "腳本自己設 REDDIT_TRACKER_NO_DOTENV=1，不讀 .env、不開 production DB；"
        "只寫 data/work/1027_e11.db，額度檔 data/work/llm-quota-e11.json，"
        f"新的 Codex 呼叫上限 {MAX_ATTEMPTS} 次（記者→必要時查核→文稿編輯）。"
        f"錄完用 `{CHECK_COMMAND}` 檢查，再把 {EVIDENCE_NAME} 與 {RECORDS_NAME} commit。"
        "回歸集 E11.json 的 xfail 已於 2026-11-13 拿掉，這個重播是 E11 條件唯一的把關。"
    )


def run_roles(
    session: Session, client, *, spec: dict, evidence: list[EvidenceItem]
) -> StoryVersion:
    """一則稿走完記者與文稿編輯。文稿編輯只看頭版，所以這則放成頭版主稿。"""
    story = add_story(session, edition_date=DAY, run_variant="mas", spec=spec)
    review_one(
        session,
        edition_date=DAY,
        story=story,
        evidence=evidence,
        client=client,
        now=NOW,
    )
    add_page_plan(
        session,
        edition_date=DAY,
        run_variant="mas",
        now=NOW,
        slots={
            "front": {"lead": story.id, "second": [], "briefs": []},
            "sections": {spec["section"]: [{"story_id": story.id, "display": "full"}]},
        },
    )
    _copy_edit_front(
        session,
        edition_date=DAY,
        client=client,
        clock=Clock(NOW),
        degraded=[],
    )
    version = latest_version(session, story.id)
    if version is None:
        raise RuntimeError("E11 沒有寫出稿件版本")
    return version


def insert_source_items(session: Session, rows: list[dict]) -> None:
    """重播時文稿編輯若 CHALLENGE，會用素材 id 重組證據包，所以要把原列放回來。"""
    for row in rows:
        data = dict(row)
        data["published_at"] = datetime.fromisoformat(data["published_at"])
        data["first_seen_at"] = datetime.fromisoformat(data["first_seen_at"])
        session.add(SourceItem(**data))
    session.flush()


def _source_payload(item: SourceItem) -> dict:
    return {
        "id": item.id,
        "source_id": item.source_id,
        "section": item.section,
        "tier": item.tier,
        "item_key": item.item_key,
        "url": item.url,
        "canonical_url": item.canonical_url,
        "title": item.title,
        "summary": item.summary,
        "lang": item.lang,
        "published_at": item.published_at.isoformat(),
        "published_at_estimated": bool(item.published_at_estimated),
        "first_seen_at": item.first_seen_at.isoformat(),
        "title_fingerprint": item.title_fingerprint,
        # 重播只需要這幾列組證據；不重建 duplicate FK。
        "duplicate_of_id": None,
    }


def _cluster_engine(db_path: Path):
    """與回歸 runner 相同的逐輪聚合，寫進 `db_path`。不呼叫 LLM。"""
    from reddit_tracker.collection.clustering import cluster_recent_items
    from reddit_tracker.config import get_settings

    data = load_items()
    registry = load_registry(get_settings().news_sources_path)
    engine = create_engine(f"sqlite:///{db_path}", future=True)
    Base.metadata.create_all(engine)
    duplicates = recomputed_duplicates(data["items"])
    pending = sorted(data["items"], key=lambda item: item["first_seen_at"])
    for run_at in data["cluster_runs_utc"]:
        batch = [
            item for item in pending if _utc(item["first_seen_at"]) <= _utc(run_at)
        ]
        pending = pending[len(batch) :]
        _insert_items(engine, batch, duplicates)
        with Session(engine) as session:
            cluster_recent_items(
                session,
                now=_utc(run_at),
                general_sources=registry.general_source_ids(),
                disabled_sources=registry.disabled_source_ids(),
            )
            session.commit()
    if pending:
        engine.dispose()
        raise RuntimeError("有素材晚於最後一輪聚合")
    return engine


def describe_story(session: Session) -> dict:
    """用 E11 的 event_titles 找到那一則，並套現行分版。"""
    from reddit_tracker.daily import run as run_module

    case = load_case()
    wanted = {norm_title(title) for title in case["event_titles"]}
    items = list(session.scalars(select(SourceItem)))
    anchors = [item for item in items if norm_title(item.title) in wanted]
    if len(anchors) != 1 or anchors[0].cluster_id is None:
        found = [(item.id, item.cluster_id, item.title) for item in anchors]
        raise RuntimeError(f"E11 錨點應該剛好一篇且已聚合，實際 {found}")
    anchor = anchors[0]
    members = [item for item in items if item.cluster_id == anchor.cluster_id]
    cluster = session.get(StoryCluster, anchor.cluster_id)
    if cluster is None:
        raise RuntimeError(f"找不到 cluster {anchor.cluster_id}")
    scored = ScoredCluster(cluster.id, cluster.section, kind_for(cluster), 0.0)
    registry = load_registry()
    rewrite_sections(session, [scored], registry=registry)
    pack = run_module.story_evidence(session, scored, registry)
    if not pack.items:
        raise RuntimeError("E11 證據包是空的")
    stat = next((item for item in items if item.title == STAT_TITLE), None)
    spec = {
        "keeper_cluster_id": cluster.id,
        "merged_cluster_ids": [],
        "section": scored.section,
        "kind": scored.kind,
        "score": 0,
        "evidence_item_ids": [item.item_id for item in pack.items],
        "anchor_item_id": pack.items[0].item_id,
    }
    return {
        "case_id": "E11",
        "anchor_item_id": anchor.id,
        "anchor_title": anchor.title,
        "cluster_id": cluster.id,
        "member_ids": [item.id for item in members],
        "section": scored.section,
        "kind": scored.kind,
        "original_section": scored.signals.get("original_section"),
        "section_rule": scored.signals.get("section_rule"),
        "source_ids": [item.source_id for item in pack.items],
        "stat_item_id": None if stat is None else stat.id,
        "stat_same_cluster": bool(
            stat is not None and stat.cluster_id == anchor.cluster_id
        ),
        "spec": spec,
        "evidence": [asdict(item) for item in pack.items],
        "source_items": [_source_payload(item) for item in members],
        "note": (
            f"MarketWatch item {anchor.id} 自成 cluster {cluster.id}，"
            f"分版 {scored.signals.get('original_section')}→{scored.section}"
            f"（{scored.signals.get('section_rule')}）。"
            + (
                f"STAT item {stat.id}（刊出稿的另一家，摘要才有 2027 FDA）"
                f"在 cluster {stat.cluster_id}，不併進這包證據。"
                if stat is not None and stat.cluster_id != anchor.cluster_id
                else "沒有把其他 Moderna／STAT 稿併進來。"
            )
        ),
    }


def prepare_story(db_path: Path) -> dict:
    """把 10/27 fixture 聚進 `db_path`（會先清掉該檔；已有的 llm_records 會放回）。不呼叫 LLM。"""
    from reddit_tracker.llm.records import restore_records, saved_records

    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    saved = saved_records(db_path) if db_path.exists() else []
    for suffix in ("", "-wal", "-shm"):
        Path(f"{db_path}{suffix}").unlink(missing_ok=True)
    engine = _cluster_engine(db_path)
    try:
        with Session(engine) as session:
            story = describe_story(session)
    finally:
        engine.dispose()
    if saved:
        restore_records(db_path, saved)
    return story


def evidence_items(rows: list[dict]) -> list[EvidenceItem]:
    return [EvidenceItem(**row) for row in rows]


class TrackingReplay(ReplayClient):
    """`logs_attempts`：complete_logged 不要再把重播寫進 llm_records。"""

    logs_attempts = True

    def __init__(self, records, *, model: str) -> None:
        super().__init__(records, model=model)
        self.used: list[dict] = []

    def complete(self, **kwargs):
        self.used.append(kwargs)
        return super().complete(**kwargs)


def replay_recorded(
    session: Session,
    *,
    records_path: Path | None = None,
    evidence_path: Path | None = None,
):
    """用已錄的 fixture 重跑同一則。缺檔或對不上 hash 都丟錯，不呼叫 Codex。"""
    records_path = Path(records_path or RECORDS)
    evidence_path = Path(evidence_path or EVIDENCE)
    story = json.loads(evidence_path.read_text(encoding="utf-8"))
    rows = json.loads(records_path.read_text(encoding="utf-8"))
    if not rows or not all(
        row.get("ok") and row.get("provider") == "codex" for row in rows
    ):
        raise RuntimeError(f"{records_path.name} 不是真 Codex 的 ok 紀錄")
    models = {row["model"] for row in rows}
    if len(models) != 1:
        raise RuntimeError(f"E11 錄音的 model 不一致：{models}")
    insert_source_items(session, story["source_items"])
    client = TrackingReplay(load_records(records_path), model=next(iter(models)))
    version = run_roles(
        session,
        client,
        spec=story["spec"],
        evidence=evidence_items(story["evidence"]),
    )
    by_hash = {row["request_hash"]: row for row in rows}
    used_roles = []
    for call in client.used:
        key = request_hash(
            system=call["system"],
            prompt=_prompt(call["messages"]),
            model=client.model,
            schema=call.get("json_schema"),
        )
        role = by_hash.get(key, {}).get("role")
        used_roles.append(role)
    return version, client, rows, used_roles


def _prompt(messages: list[dict]) -> str:
    from reddit_tracker.llm.replay import prompt_text

    return prompt_text(messages)


def check_recorded() -> int:
    """`--check`：只重播。缺錄音回 2；重播失敗或標題仍踩到禁止樣式回 1。"""
    if not RECORDS.is_file() or not EVIDENCE.is_file():
        print(missing_recording_message())
        return 2
    engine = create_engine("sqlite://", future=True)
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        version, client, _rows, used_roles = replay_recorded(session)
    engine.dispose()
    problems = headline_violations(version.headline)
    print(
        f"[e11] headline={version.headline!r} roles={used_roles} misses={len(client.misses)}"
    )
    if (
        client.misses
        or problems
        or "reporter" not in used_roles
        or "copy_editor" not in used_roles
    ):
        for key in client.misses:
            print(f"[e11] miss {key}")
        for pattern in problems:
            print(f"[e11] headline matches {pattern}")
        return 1
    return 0


def reloaded_evidence(session: Session, story: dict) -> list[EvidenceItem]:
    """文稿編輯 CHALLENGE 之後會用這條路重組證據；要和錄音時的證據包一致。"""
    registry = load_registry()
    names = {source.id: source.name for source in registry.sources}
    return build_evidence_from_ids(
        session,
        list(story["spec"]["evidence_item_ids"]),
        names,
        anchor_item_id=story["spec"].get("anchor_item_id"),
    ).items

"""P3-1：run_mas 只為分版主編看得到的候選建 Story 列（候選池＋全站前 10＋既有列）。"""
import json
import random
from types import SimpleNamespace

from sqlalchemy import func, select

from reddit_tracker.daily.mas import orchestrator
from reddit_tracker.daily.mas.orchestrator import (
    GLOBAL_TOP_N, SECTIONS, _default_pitches, mas_story_keepers, run_mas, section_pool,
)
from reddit_tracker.daily.scoring import DESK_POOL_PER_SECTION, SECTION_QUOTAS
from reddit_tracker.models import Story
from tests.test_mas_steps import DAY, NOW, Scripted, _checker, _item, _registry, _snapshot


def _raw(keeper, section, kind="report", score=10, evidence=True):
    return {"keeper_cluster_id": keeper, "section": section, "kind": kind, "score": score,
            "evidence_item_ids": [keeper] if evidence else []}


def _has(raw):
    return raw["evidence_item_ids"]


def _brute_force(candidates):
    """舊做法：每個候選都建一列（id＝快照位置），再用正式的 section_pool／排序挑。"""
    stories = [SimpleNamespace(id=i, keeper=r["keeper_cluster_id"], section=r["section"], kind=r["kind"],
                               score=r.get("score") or 0) for i, r in enumerate(candidates)]
    evidence = {s.id: (["x"] if _has(candidates[s.id]) else []) for s in stories}
    seen = set()
    for section in SECTIONS:
        seen |= {s.keeper for s in section_pool(stories, evidence, section)}
    top = sorted((s for s in stories if s.section in SECTIONS), key=lambda s: -s.score)[:GLOBAL_TOP_N]
    seen |= {s.keeper for s in top}
    default = {stories[p.story_id].keeper for p in _default_pitches(stories, evidence)}
    return seen, default


def test_pool_per_section_skips_stories_without_evidence():
    candidates = [_raw(s * 100 + j, s_name, score=100 - j, evidence=j != 0)
                  for s, s_name in enumerate(SECTIONS) for j in range(12)]
    keepers = mas_story_keepers(candidates, {}, _has)
    per_section = {s: sum(1 for k in keepers if k // 100 == i) for i, s in enumerate(SECTIONS)}
    assert per_section == {s: SECTION_QUOTAS[s] * DESK_POOL_PER_SECTION + 1 for s in SECTIONS}  # +1：前 10 的無證據稿
    assert keepers == [r["keeper_cluster_id"] for r in candidates if r["keeper_cluster_id"] in set(keepers)]


def test_global_top_includes_other_sections_and_evidenceless_but_not_low_scores():
    candidates = [_raw(1, "finance", score=500), _raw(2, "taiwan", score=400, evidence=False),
                  _raw(3, "sports", score=1), _raw(4, "tech", kind="social", score=2)]
    candidates += [_raw(10 + j, "world", score=50 - j) for j in range(10)]
    keepers = set(mas_story_keepers(candidates, {}, _has))
    # world 池 8 篇（10–17）；前 10 是 2 加上 10–18（finance 不是內版，social 只有 2 分排不進）
    assert keepers == {2, *range(10, 19)}


def test_matches_creating_every_row_on_random_snapshots():
    rng = random.Random(1127)
    sections = [*SECTIONS, "finance", "sports"]
    for _ in range(200):
        candidates = [_raw(k, rng.choice(sections), kind=rng.choice(["report", "single_source", "social"]),
                           score=rng.choice([0, 1, 2, 5, 10, 20, 50]), evidence=rng.random() > 0.2)
                      for k in rng.sample(range(1, 10_000), rng.randint(0, 80))]
        old, default = _brute_force(candidates)
        new = set(mas_story_keepers(candidates, {}, _has))
        assert new == old and default <= new


def test_existing_rows_are_not_returned_but_keep_their_place(session):
    existing = {7: Story(id=1, edition_date=DAY, run_variant="mas", keeper_cluster_id=7, section="tech",
                         kind="report", score=10, merged_cluster_ids=[])}
    candidates = [_raw(7, "tech", score=10)] + [_raw(20 + j, "tech", score=10) for j in range(10)]
    keepers = mas_story_keepers(candidates, existing, _has)
    # 既有列（keeper 7）平手排第一、占一個池位，但不回傳；池裡新列是 20–26，前 10 再加 27、28
    assert keepers == list(range(20, 29))


def test_run_mas_builds_rows_only_for_the_pool(session, monkeypatch):
    raw = []
    for i, section in enumerate(SECTIONS):
        for j in range(12):
            item = _item(session, f"事件{i}-{j}", "摘要", url=f"https://www.cna.com.tw/{i}/{j}")
            raw.append(_snapshot([item.id], i * 100 + j, section=section, score=100 - j))
    extra = _item(session, "財經大事", "摘要", url="https://www.cna.com.tw/f")
    raw.append(_snapshot([extra.id], 999, section="finance", score=1000))
    built = []
    real = orchestrator.build_evidence_from_ids
    monkeypatch.setattr(orchestrator, "build_evidence_from_ids", lambda *a, **k: built.append(1) or real(*a, **k))
    seen_top = []

    def handler(kw):
        if "分版主編" in kw["system"]:
            data = json.loads(kw["messages"][0]["content"])
            seen_top.append([t["story_id"] for t in data["global_top10"]])
            return json.dumps({"pitches": []})
        if "記者" in kw["system"]:
            return json.dumps({"action": "DRAFT", "headline": "標題", "body": "內文。[S1]"})
        if "總編輯" in kw["system"]:
            data = json.loads(kw["messages"][0]["content"])
            ids = [p["story_id"] for p in data["front"]][:6]
            return json.dumps({"lead": ids[0] if ids else None, "second": ids[1:5], "briefs": ids[5:],
                               "links": [], "reasons": [], "dropped": []})
        return _checker("OK", "")

    run_mas(session, edition_date=DAY, snapshot=SimpleNamespace(candidates=raw), registry=_registry(),
            client=Scripted(handler), now=NOW)
    rows = session.scalar(select(func.count()).select_from(Story).where(Story.run_variant == "mas"))
    assert rows == 3 * SECTION_QUOTAS["taiwan"] * DESK_POOL_PER_SECTION  # 前 10 都在池裡，finance 不是內版
    assert len(built) == rows  # 池外的候選連證據包都不建
    assert len(seen_top) == 3 and all(len(t) == GLOBAL_TOP_N for t in seen_top)
    keepers = set(session.scalars(select(Story.keeper_cluster_id)))
    assert 999 not in keepers and {j for j in range(8)} <= keepers and 8 not in keepers

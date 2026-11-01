"""同一事件見報兩次的回歸（2026-10-31 幣安、2026-11-01 台北市長辯論；不呼叫 LLM）。

fixture `desk_1031_1101.json` 是 production 複本裡這幾個事件的成員素材（標題、摘要前 300 字；
18416、14829 各取 20 篇）：

- 10/31：LLM 編輯會議正確提出 [[14963, 16914, 14305]]（中文幣安＋兩個英文 Binance），程式確認時
  中文標題只有「幣安」、譯名表沒有，14963 被剔除，國際版與科技版各刊一篇。
- 11/01：事件 13410 的代表稿是 10/29 高雄市長辯論，25 篇成員裡 23 篇是台北市長辯論，證據包 S1 也是
  台北；LLM 只看到「高雄」標題，沒和台北辯論 18416 併，台北辯論刊了兩篇（5327、5330）。
- 不能過度合併：高雄 14829 與台北 18416 是兩場辯論；日月光財報 12444 與幣安無關。
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest

from reddit_tracker.collection.entities import EntityContext, MergeRules, load_lexicon
from reddit_tracker.daily import run as run_module
from reddit_tracker.daily.desk import alias_shared, confirm_groups, load_cluster_titles
from reddit_tracker.daily.scoring import ScoredCluster
from reddit_tracker.models import SourceItem, StoryCluster
from reddit_tracker.seeds.news_sources import load_registry

FIXTURE = Path(__file__).parent / "regression" / "fixtures" / "desk_1031_1101.json"
CLUSTERS = {c["cluster_id"]: c for c in json.loads(FIXTURE.read_text(encoding="utf-8"))}
REGISTRY = load_registry()


def _dt(text: str) -> datetime:
    return datetime.fromisoformat(text)


@pytest.fixture()
def desk_db(session):
    for cluster in CLUSTERS.values():
        items = cluster["items"]
        session.add(StoryCluster(
            id=cluster["cluster_id"], lang_group=cluster["lang_group"], section=cluster["section"],
            title=cluster["title"], representative_item_id=cluster["representative_item_id"],
            first_published_at=min(_dt(i["published_at"]) for i in items),
            last_published_at=max(_dt(i["published_at"]) for i in items),
            created_at=_dt(items[0]["first_seen_at"]), updated_at=_dt(items[-1]["first_seen_at"]),
        ))
        for item in items:
            session.add(SourceItem(
                id=item["id"], source_id=item["source_id"], section=item["section"], tier=item["tier"],
                item_key=str(item["id"]), url=item["url"], canonical_url=item["canonical_url"], title=item["title"],
                summary=item["summary"], lang=item["lang"], published_at=_dt(item["published_at"]),
                first_seen_at=_dt(item["first_seen_at"]), duplicate_of_id=item["duplicate_of_id"],
                cluster_id=cluster["cluster_id"],
            ))
    session.flush()
    return session


def _confirm(session, groups):
    lexicon = load_lexicon()
    ids = sorted({i for g in groups for i in g})
    titles = load_cluster_titles(session, ids, lexicon, REGISTRY.disabled_source_ids())
    context = EntityContext(e for t in titles.values() for e in t.entities)
    return confirm_groups(groups, titles, lexicon, context, MergeRules().llm_merge_min_entities), titles, context


def test_summary_alias_confirms_the_llm_binance_merge(desk_db):
    (confirmed, rejected), titles, context = _confirm(desk_db, [[14963, 16914, 14305]])
    assert confirmed == [[14963, 16914, 14305]] and rejected == []
    assert "binance" in titles[14963].aliases  # 「幣安(Binance)」寫在中文摘要裡
    assert "binance" in alias_shared(titles[14963], titles[16914], context)


def test_summary_alias_does_not_confirm_unrelated_llm_merges(desk_db):
    (confirmed, rejected), _, _ = _confirm(desk_db, [[14963, 12444]])
    assert confirmed == [] and {r["cluster_id"] for r in rejected} == {14963, 12444}


def test_lead_title_is_what_the_story_will_be_written_about(desk_db):
    pool = [ScoredCluster(13410, "taiwan", "report", 34.1), ScoredCluster(18416, "taiwan", "report", 48.4),
            ScoredCluster(14829, "taiwan", "report", 45.5)]
    leads = run_module.lead_titles(desk_db, pool, REGISTRY)
    assert "高雄" in CLUSTERS[13410]["title"]
    assert "台北" in leads[13410] and "高雄" not in leads[13410]
    assert "高雄" in leads[14829] and "台北" in leads[18416]


class TitleJudge:
    """假的編輯會議 LLM：只憑標題判斷，標題都有「台北市長」或都有「高雄市長」才算同一事件。"""

    name = "fake"

    def __init__(self):
        self.requests = 0
        self.seen: dict[int, str] = {}

    def find_same_events(self, candidates):
        self.requests += 1
        self.seen = dict(candidates)
        groups = []
        for city in ("台北市長", "高雄市長"):
            ids = [i for i, title in candidates if city in title]
            if len(ids) >= 2:
                groups.append(ids)
        return groups


def _meeting(session, lead_titles):
    scored = [ScoredCluster(18416, "taiwan", "report", 48.4), ScoredCluster(14829, "taiwan", "report", 45.5),
              ScoredCluster(13410, "taiwan", "report", 34.1)]
    judge = TitleJudge()
    merged, desk = run_module._editorial_meeting(
        session, scored, judge, REGISTRY.disabled_source_ids(), lead_titles,
    )
    return merged, desk, judge


def test_editorial_meeting_merges_the_two_taipei_debate_clusters(desk_db):
    pool = [ScoredCluster(i, "taiwan", "report", 1) for i in (18416, 14829, 13410)]
    merged, desk, judge = _meeting(desk_db, run_module.lead_titles(desk_db, pool, REGISTRY))
    assert "台北" in judge.seen[13410]
    assert desk.llm_groups == [[18416, 13410]] and desk.groups == [[18416, 13410]]
    keepers = {c.cluster_id: c.merged_ids for c in merged}
    assert keepers == {18416: [13410], 14829: []}  # 高雄辯論 14829 仍是另一則


def test_without_lead_titles_the_stale_representative_hides_the_duplicate(desk_db):
    # 修正前的行為：LLM 看到 13410 的代表標題（高雄）→ 把它和高雄 14829 歸成一組；台北辯論仍見報兩次
    merged, desk, judge = _meeting(desk_db, None)
    assert "高雄" in judge.seen[13410]
    assert [18416, 13410] not in desk.groups

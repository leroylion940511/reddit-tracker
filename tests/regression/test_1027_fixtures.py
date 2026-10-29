"""步驟 0 匯出的 10/27 fixture：存在、格式正確、互相對得上。不依賴母本。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


def _load(name: str):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def groups() -> dict[str, list[int]]:
    return _load("1027_groups.json")


@pytest.fixture(scope="module")
def merges() -> list[list[int]]:
    return _load("1027_merges.json")


@pytest.fixture(scope="module")
def meta() -> dict:
    return _load("1027_meta.json")


def test_groups_format(groups):
    assert groups
    for cluster_id, items in groups.items():
        assert cluster_id.isdigit()
        assert items and all(isinstance(i, int) for i in items)
        assert len(items) == len(set(items))
    every_item = [i for items in groups.values() for i in items]
    assert len(every_item) == len(set(every_item)), "一篇素材只能屬於一個事件"


def test_merges_format_and_match_cluster_version(groups, merges, meta):
    cluster_groups = meta["merged_groups_cluster_ids"]
    assert len(merges) == len(cluster_groups)
    for items, cluster_ids in zip(merges, cluster_groups):
        assert all(isinstance(i, int) for i in items)
        assert items == [i for cid in cluster_ids for i in groups[str(cid)]]


def test_published_clusters_are_covered(groups, meta):
    assert len(meta["articles"]) == 42
    for article in meta["articles"]:
        for cid in [article["cluster_id"], *article["merged_cluster_ids"]]:
            assert str(cid) in groups


def test_e01_football_item_came_from_cross_language_merge(groups, meta):
    """E01：AP 美式足球稿本來在英文 NFL 事件，是 find_same_events 把整組併進中文塞爾維亞事件。"""
    (item,) = meta["e01"]["items"]
    assert item["source_item_id"] == 1053
    assert item["cluster_id"] == 403 and item["cluster_lang_group"] == "en"
    assert 1053 in groups["403"] and 1053 not in groups["410"]
    assert item["merged_groups_containing_cluster"] == [[403, 410]]
    assert item["published_in_articles"][0]["cluster_id"] == 410
    serbia = next(a for a in meta["articles"] if a["cluster_id"] == 410)
    assert serbia["merged_cluster_ids"] == [403]

"""Story clustering: tokenization, outlets, incremental assignment, cluster signals."""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from reddit_tracker.collection.clustering import (
    cluster_recent_items,
    lang_group,
    outlet_of,
    tokenize,
)
from reddit_tracker.models import SourceItem, StoryCluster

NOW = datetime(2026, 10, 27, 2, 0, tzinfo=timezone.utc)


def _item(session, source_id, url, title, summary="", *, lang="zh-Hant", section="taiwan",
           tier="T2", hours_ago=1, duplicate_of=None):
    item = SourceItem(
        source_id=source_id, section=section, tier=tier,
        item_key=hashlib.sha1(f"{source_id}{url}".encode()).hexdigest(),
        url=url, canonical_url=url, title=title, summary=summary, lang=lang,
        published_at=NOW - timedelta(hours=hours_ago), first_seen_at=NOW,
        duplicate_of_id=duplicate_of,
    )
    session.add(item)
    session.flush()
    return item


def test_tokenize_bigrams_converts_simplified_and_strips_boilerplate():
    traditional = tokenize("塞爾維亞總統承認敗選", "zh-Hant")
    simplified = tokenize("塞尔维亚总统承认败选", "zh")
    assert traditional == simplified
    assert "塞爾" in traditional
    assert tokenize("（中央社記者王小明台北26日電）沈伯洋 115年10月26日", "zh-Hant") == ["沈伯", "伯洋"]
    assert tokenize("The election results: Lula wins 2026 https://x.com/a comments points", "en") == [
        "election", "results", "lula", "wins", "2026",
    ]


def test_lang_group_and_outlet():
    assert lang_group("zh") == lang_group("zh-Hant") == "zh"
    assert lang_group("en") == "en"
    assert outlet_of("https://news.ltn.com.tw/news/1", None, None) == "ltn.com.tw"
    assert outlet_of("https://feeds.bbc.co.uk/news/1", None, None) == "bbc.co.uk"
    assert outlet_of("https://apnews.com/article/x", None, None) == "apnews.com"
    assert outlet_of("https://tw.news.yahoo.com/x", "標題", "（中央社記者王小明台北26日電）內文") == "cna.com.tw"


def test_same_event_from_two_outlets_becomes_one_cluster(session):
    _item(session, "cna-world", "https://cna.com.tw/1", "塞爾維亞國會大選 武契奇承認敗選",
          "學生運動終結長期執政，塞爾維亞總統武契奇承認敗選", section="world", hours_ago=5)
    _item(session, "ltn-world", "https://news.ltn.com.tw/2", "武契奇認輸 塞爾維亞大選反對派勝出",
          "塞爾維亞國會大選，總統武契奇承認敗選，學生運動勝出", section="world", hours_ago=4)
    _item(session, "dw-chinese", "https://dw.com/3", "武契奇承认败选 塞尔维亚学生运动赢得议会选举",
          "塞尔维亚总统武契奇承认败选", lang="zh", section="world", hours_ago=3)
    _item(session, "cna-sports", "https://cna.com.tw/4", "味全龍三連勝奪下台灣大賽冠軍",
          "中職台灣大賽第四戰，味全龍擊敗中信兄弟", section="sports", hours_ago=2)

    stats = cluster_recent_items(session, now=NOW)

    assert (stats.window_items, stats.new_clusters, stats.joined_existing) == (4, 2, 2)
    serbia = session.scalar(select(StoryCluster).where(StoryCluster.section == "world"))
    assert serbia.item_count == 3
    assert serbia.outlet_count == 3
    assert serbia.title == "塞爾維亞國會大選 武契奇承認敗選"


def test_different_languages_and_distant_times_do_not_merge(session):
    _item(session, "bbc-world", "https://bbc.co.uk/1", "Serbia election Vucic concedes defeat",
          "Serbia election student movement wins", lang="en", section="world")
    _item(session, "cna-world", "https://cna.com.tw/1", "Serbia election Vucic concedes defeat 塞爾維亞",
          "塞爾維亞總統承認敗選", section="world")
    _item(session, "cna-world", "https://cna.com.tw/2", "塞爾維亞總統承認敗選 學生運動勝選",
          "塞爾維亞總統承認敗選", section="world", hours_ago=60)

    stats = cluster_recent_items(session, now=NOW)

    assert stats.new_clusters == 3


def test_incremental_run_keeps_existing_assignment_and_inherits_for_duplicates(session):
    first = _item(session, "cna-world", "https://cna.com.tw/1", "日本前首相福田康夫逝世 享年90歲",
                  "日本前首相福田康夫去世，享年90歲", section="world", hours_ago=6)
    cluster_recent_items(session, now=NOW)
    original_cluster = first.cluster_id

    later = _item(session, "rfi-chinese", "https://rfi.fr/2", "日本前首相福田康夫逝世 中国表示哀悼",
                  "日本前首相福田康夫去世，享年90岁", lang="zh", section="world", hours_ago=2)
    copy = _item(session, "cna-headlines", "https://cna.com.tw/1", "日本前首相福田康夫逝世 享年90歲",
                 section="taiwan", duplicate_of=first.id)
    stats = cluster_recent_items(session, now=NOW)

    assert first.cluster_id == original_cluster
    assert later.cluster_id == original_cluster
    assert copy.cluster_id == original_cluster
    assert (stats.new_clusters, stats.joined_existing, stats.duplicates_assigned) == (0, 1, 1)
    cluster = session.get(StoryCluster, original_cluster)
    assert cluster.item_count == 3
    assert cluster.outlet_count == 2  # cna-headlines 是同一家中央社


def test_general_feeds_do_not_vote_section_and_social_is_not_an_outlet(session):
    for n in range(3):
        _item(session, "rti-news", f"https://rti.org.tw/{n}", f"巴西總統大選魯拉逆轉連任 第{n}報",
              "巴西總統決選，魯拉擊敗佛拉維歐成功連任", section="taiwan", hours_ago=5 - n)
    _item(session, "ltn-world", "https://news.ltn.com.tw/9", "魯拉贏得巴西總統大選 逆轉連任",
          "巴西總統決選，魯拉擊敗佛拉維歐連任", section="world", hours_ago=1)
    _item(session, "ptt-gossiping", "https://ptt.cc/1", "[新聞] 巴西總統大選魯拉逆轉連任",
          "巴西總統決選 魯拉擊敗佛拉維歐連任", section="social", tier="T4", hours_ago=1)

    cluster_recent_items(session, now=NOW, general_sources=frozenset({"rti-news"}))

    cluster = session.scalar(select(StoryCluster))
    assert cluster.section == "world"
    assert cluster.item_count == 5
    assert cluster.outlet_count == 2
    assert cluster.t4_count == 1


def test_representative_prefers_higher_tier(session):
    _item(session, "reddit-like", "https://ptt.cc/1", "央行宣布升息半碼 房貸族壓力增加",
          "中央銀行理監事會決議升息半碼", section="social", tier="T4", hours_ago=5)
    _item(session, "cbc-news", "https://cbc.gov.tw/1", "央行理監事會決議升息半碼",
          "中央銀行理監事會決議升息半碼，房貸族壓力增加", section="finance", tier="T1", hours_ago=2)

    cluster_recent_items(session, now=NOW)

    cluster = session.scalar(select(StoryCluster))
    assert cluster.item_count == 2
    assert cluster.title == "央行理監事會決議升息半碼"
    assert cluster.section == "finance"

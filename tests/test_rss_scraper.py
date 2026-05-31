"""RssScraper basic parsing tests.

不打網路 — sample XML 直接 inline. 重點覆蓋:
- 標準 entry 解析（subreddit feed 來源）
- HTML selftext 去 tag / 去 "submitted by ..." 樣板
- user feed (entry-level category 帶 sub)
- 缺欄位 / 壞 XML graceful
- search / fetch_post / fetch_duplicates / fetch_user_about / fetch_comment_tree
  全 raise NotImplementedError（Plan C 階段該層 disable 的契約）
"""
from __future__ import annotations

import pytest

from reddit_tracker.scrapers.rss import RssScraper


UA = "reddit_tracker/0.1 by tester"


SUB_FEED_SAMPLE = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <category term="tifu" label="r/tifu"/>
  <title>newest submissions : tifu</title>
  <entry>
    <author><name>/u/alice</name></author>
    <category term="tifu" label="r/tifu"/>
    <content type="html">&lt;!-- SC_OFF --&gt;&lt;div class="md"&gt;&lt;p&gt;Hello &lt;b&gt;world&lt;/b&gt;.&lt;/p&gt;&lt;/div&gt;&lt;!-- SC_ON --&gt; submitted by &lt;a href="https://www.reddit.com/user/alice"&gt;/u/alice&lt;/a&gt; [link] [comments]</content>
    <id>t3_abc123</id>
    <link href="https://www.reddit.com/r/tifu/comments/abc123/test_post/" />
    <updated>2026-05-31T06:01:21+00:00</updated>
    <published>2026-05-31T06:01:21+00:00</published>
    <title>Test post title</title>
  </entry>
  <entry>
    <author><name>/u/bob</name></author>
    <category term="tifu" label="r/tifu"/>
    <content type="html">&lt;p&gt;Bare HTML without SC markers&lt;/p&gt;</content>
    <id>t3_def456</id>
    <link href="https://www.reddit.com/r/tifu/comments/def456/another/" />
    <published>2026-05-31T05:00:00+00:00</published>
    <title>Second post</title>
  </entry>
</feed>
"""


USER_FEED_SAMPLE = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>overview for spez</title>
  <entry>
    <author><name>/u/spez</name></author>
    <category term="announcements" label="r/announcements"/>
    <content type="html">&lt;p&gt;hi&lt;/p&gt; submitted by /u/spez</content>
    <id>t3_xyz789</id>
    <link href="https://www.reddit.com/r/announcements/comments/xyz789/foo/" />
    <published>2026-05-30T10:00:00+00:00</published>
    <title>Announcement</title>
  </entry>
</feed>
"""


def _scraper() -> RssScraper:
    return RssScraper(user_agent=UA, min_interval_seconds=0.0)


def test_parse_sub_feed_basic_fields():
    posts = _scraper()._parse_feed(SUB_FEED_SAMPLE, default_subreddit="tifu")
    assert len(posts) == 2
    p = posts[0]
    assert p.reddit_post_id == "abc123"
    assert p.subreddit == "tifu"
    assert p.title == "Test post title"
    assert p.author == "alice"
    assert p.permalink == "/r/tifu/comments/abc123/test_post/"
    assert p.url == "https://www.reddit.com/r/tifu/comments/abc123/test_post/"
    # selftext: 去 HTML tag + 去 "submitted by ..." 尾巴
    assert "Hello world" in p.selftext
    assert "submitted by" not in p.selftext.lower()
    assert "<b>" not in p.selftext
    # 來源 flag
    assert p.extras == {"source": "rss"}
    # engagement 全空（RSS 無）
    assert p.score == 0
    assert p.num_comments == 0
    assert p.author_karma is None
    assert p.upvote_ratio is None
    # 時間有解到
    assert p.created_utc.year == 2026
    assert p.created_utc.month == 5


def test_parse_sub_feed_strips_html_without_sc_markers():
    posts = _scraper()._parse_feed(SUB_FEED_SAMPLE, default_subreddit="tifu")
    assert posts[1].selftext == "Bare HTML without SC markers"


def test_parse_user_feed_picks_subreddit_per_entry():
    """user feed 沒 default subreddit, 每個 entry 帶自己的 category."""
    posts = _scraper()._parse_feed(USER_FEED_SAMPLE, default_subreddit=None)
    assert len(posts) == 1
    assert posts[0].subreddit == "announcements"
    assert posts[0].author == "spez"


def test_parse_feed_handles_malformed_xml():
    assert _scraper()._parse_feed("<<<not xml", default_subreddit="x") == []


def test_parse_feed_handles_empty_feed():
    empty = '<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom"/>'
    assert _scraper()._parse_feed(empty, default_subreddit="x") == []


def test_entry_without_t3_prefix_skipped():
    xml = """<?xml version="1.0"?>
    <feed xmlns="http://www.w3.org/2005/Atom">
      <entry>
        <id>not_a_post_id</id>
        <title>Bad</title>
      </entry>
    </feed>"""
    assert _scraper()._parse_feed(xml, default_subreddit="x") == []


@pytest.mark.parametrize("method,args", [
    ("fetch_post", ("abc",)),
    ("fetch_duplicates", ("abc",)),
    ("fetch_user_about", ("alice",)),
    ("fetch_comment_tree", ("abc",)),
])
def test_unsupported_methods_raise(method, args):
    s = _scraper()
    with pytest.raises(NotImplementedError):
        getattr(s, method)(*args)


def test_search_returns_empty_with_one_warning(caplog):
    """search() 在 Plan C 階段是 silent no-data, 只 warn 一次避免洗版."""
    import logging
    s = _scraper()
    with caplog.at_level(logging.WARNING, logger="reddit_tracker.scrapers.rss"):
        assert s.search("query") == []
        assert s.search("another") == []
        assert s.search("third") == []
    warns = [r for r in caplog.records if "search()" in r.message]
    assert len(warns) == 1, "應該只 warn 一次"


def test_user_agent_required_and_must_contain_marker():
    with pytest.raises(ValueError):
        RssScraper(user_agent="")
    with pytest.raises(ValueError):
        RssScraper(user_agent="curl/7.0")
    # 帶 reddit_tracker 即可
    RssScraper(user_agent="reddit_tracker/x.y by anyone")

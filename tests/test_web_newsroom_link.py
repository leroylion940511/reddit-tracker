from datetime import date

from reddit_tracker.web import _with_newsroom_link


def test_edition_page_gets_newsroom_entry():
    html = _with_newsroom_link("<html><body><p>x</p></body></html>", date(2026, 11, 12))
    assert '/daily/2026-11-12/newsroom?variant=mas' in html
    assert '/daily/2026-11-12/newsroom?variant=pipeline' in html
    assert html.index("rt-newsroom-bar") < html.index("</body>")


def test_entry_appended_without_body_tag():
    assert "rt-newsroom-bar" in _with_newsroom_link("<p>x</p>", date(2026, 11, 12))

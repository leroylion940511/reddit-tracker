from datetime import date

from reddit_tracker.web import _with_newsroom_link


def test_edition_page_gets_newsroom_entry():
    html = _with_newsroom_link("<html><body><p>x</p></body></html>", date(2026, 11, 12))
    assert '/daily/2026-11-12/newsroom?variant=mas' in html
    assert '/daily/2026-11-12/newsroom?variant=pipeline' in html
    assert html.index("rt-newsroom-bar") < html.index("</body>")


def test_entry_appended_without_body_tag():
    assert "rt-newsroom-bar" in _with_newsroom_link("<p>x</p>", date(2026, 11, 12))


def _client(monkeypatch):
    from contextlib import contextmanager

    from fastapi.testclient import TestClient

    import reddit_tracker.daily.run as run_mod
    from reddit_tracker import web

    calls = []

    @contextmanager
    def scope():
        yield object()

    monkeypatch.setattr(web, "session_scope", scope)
    monkeypatch.setattr(web, "approve_story", lambda s, story_id, by, now: calls.append(("approve", story_id, by)))
    monkeypatch.setattr(run_mod, "refresh_after_review", lambda d, scope: calls.append(("refresh", d)))
    return TestClient(web.app), calls


def test_decision_rejects_get(monkeypatch):
    client, calls = _client(monkeypatch)
    resp = client.get("/daily/2026-11-12/newsroom/decision?story_id=1&action=approve&by=x")
    assert resp.status_code == 405 and calls == []


def test_decision_accepts_urlencoded_form_post(monkeypatch):
    client, calls = _client(monkeypatch)
    resp = client.post(
        "/daily/2026-11-12/newsroom/decision",
        data={"story_id": "7", "variant": "mas", "by": "志晨", "action": "approve"},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert resp.headers["location"] == "/daily/2026-11-12/newsroom?variant=mas&story=7"
    assert calls == [("approve", 7, "志晨"), ("refresh", date(2026, 11, 12))]


def test_decision_requires_reviewer(monkeypatch):
    client, calls = _client(monkeypatch)
    resp = client.post("/daily/2026-11-12/newsroom/decision", data={"story_id": "7", "by": " ", "action": "approve"})
    assert resp.status_code == 400 and calls == []

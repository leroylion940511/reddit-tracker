"""MAS_FULL_EVIDENCE：M 組證據包對齊 P 組；預設關閉時行為不變。"""
from types import SimpleNamespace

import pytest

from reddit_tracker.config import get_settings
from reddit_tracker.daily.mas import orchestrator
from reddit_tracker.daily.mas.orchestrator import article_domains, run_mas
from tests.test_mas_steps import DAY, NOW, Scripted, _checker, _item, _snapshot


class _Reg:
    """feed 掛在別的網域（feedburner）的中央社，加一個會連到任意網域的聚合站。"""

    def __init__(self):
        self.sources = [
            SimpleNamespace(id="cna-politics", name="中央社 政治", url="https://feeds.feedburner.com/cna"),
            SimpleNamespace(id="hn", name="Hacker News 首頁", url="https://hnrss.org/frontpage"),
            SimpleNamespace(id="off", name="停用來源", url="https://off.example/feed"),
        ]

    def disabled_source_ids(self):
        return frozenset({"off"})


def _seed(session):
    for i in range(6):
        _item(session, f"中央社稿{i}", "摘要", url=f"https://www.cna.com.tw/a{i}", source_id="cna-politics")
        _item(session, f"外連{i}", "摘要", url=f"https://site{i}.example/x", source_id="hn")
        _item(session, f"停用{i}", "摘要", url=f"https://spam.example/{i}", source_id="off")


def test_article_domains_keeps_home_domain_but_not_long_tail_or_disabled(session):
    _seed(session)
    assert article_domains(session, _Reg(), NOW) == frozenset({"cna.com.tw"})


def test_article_domains_ignores_thin_sources_and_the_future(session):
    from datetime import timedelta

    _item(session, "只有一篇", "摘要", url="https://thin.example/1", source_id="cna-politics")
    assert article_domains(session, _Reg(), NOW) == frozenset()
    _seed(session)
    assert article_domains(session, _Reg(), NOW - timedelta(days=30)) == frozenset()


def test_switch_defaults_off():
    get_settings.cache_clear()
    assert get_settings().mas_full_evidence is False


@pytest.mark.parametrize("on", [False, True])
def test_run_mas_uses_the_switch(session, monkeypatch, on):
    monkeypatch.setenv("MAS_FULL_EVIDENCE", "true" if on else "false")
    get_settings.cache_clear()
    calls = []
    real = orchestrator.build_evidence_from_ids
    monkeypatch.setattr(orchestrator, "build_evidence_from_ids",
                        lambda *a, **k: calls.append((k.get("allowed_domains"), k.get("context"))) or real(*a, **k))
    try:
        _seed(session)
        item = _item(session, "武契奇宣布國會選舉", "摘要", url="https://www.cna.com.tw/z", source_id="cna-politics")
        raw = [_snapshot([item.id], 1, section="world", score=90)]
        run_mas(session, edition_date=DAY, snapshot=SimpleNamespace(candidates=raw), registry=_Reg(),
                client=Scripted(lambda kw: _checker("OK", "")), now=NOW, pitches=[])
    finally:
        get_settings.cache_clear()
    domains, context = calls[0]
    assert ("cna.com.tw" in domains) is on and (context is not None) is on

import pytest
from pydantic import ValidationError

from reddit_tracker.seeds.news_sources import NewsSource, SourceRegistry, load_registry


SOCIAL_NOTE = "2026-10-28 停用：社群來源，不在 MVP"


def test_registry_loads_and_every_section_but_social_has_enabled_sources():
    registry = load_registry()
    sections = {s.section for s in registry.enabled()}
    # 社群觀察版的來源已全停（手冊步驟 1），其他版仍要有啟用來源。
    assert sections == set(registry.sections) - {"social"}


def test_social_sources_are_all_disabled_with_reason():
    registry = load_registry()
    social = [s for s in registry.sources if s.section == "social"]
    assert not [s.id for s in social if s.enabled]
    newly_disabled = [s for s in social if s.notes == SOCIAL_NOTE]
    kinds = [s.id.split("-")[0] for s in newly_disabled]
    assert (kinds.count("reddit"), kinds.count("ptt"), kinds.count("threads")) == (17, 6, 1)
    assert len(newly_disabled) == 24
    # 其他版不能有社群／Reddit 來源偷偷啟用
    assert not [s.id for s in registry.enabled() if s.tier == "T4" or s.method == "reddit"]
    assert registry.disabled_source_ids() >= {s.id for s in social}


def test_disabled_sources_explain_why():
    registry = load_registry()
    for source in registry.sources:
        if not source.enabled and not source.requires_key:
            assert source.notes, source.id


def _source(**overrides):
    base = dict(id="x", name="X", section="taiwan", tier="T2", method="rss",
                url="https://example.com/feed", lang="zh-Hant")
    return base | overrides


def test_rsshub_request_url_adds_base_and_key():
    source = NewsSource(**_source(method="rsshub", url="/cna/aipl"))
    assert source.request_url("http://127.0.0.1:1200/", "k1") == "http://127.0.0.1:1200/cna/aipl?key=k1"
    assert source.request_url("http://127.0.0.1:1200", None) == "http://127.0.0.1:1200/cna/aipl"


def test_rsshub_request_url_encodes_non_ascii_route():
    source = NewsSource(**_source(method="rsshub", url="/threads/search/台灣"))
    assert source.request_url("http://h", None) == "http://h/threads/search/%E5%8F%B0%E7%81%A3"


def test_reddit_request_url_uses_new_rss():
    source = NewsSource(**_source(method="reddit", url="taiwan", tier="T4", section="social"))
    assert source.request_url("http://h", None) == "https://www.reddit.com/r/taiwan/new/.rss"


@pytest.mark.parametrize("overrides", [
    {"method": "rsshub", "url": "cna/aipl"},
    {"method": "rss", "url": "http://example.com/feed"},
    {"method": "reddit", "url": "r/taiwan"},
])
def test_url_shape_is_validated(overrides):
    with pytest.raises(ValidationError):
        NewsSource(**_source(**overrides))


def test_duplicate_ids_and_unknown_sections_are_rejected():
    with pytest.raises(ValidationError):
        SourceRegistry(version=1, sections={"taiwan": "台灣"}, sources=[_source(), _source()])
    with pytest.raises(ValidationError):
        SourceRegistry(version=1, sections={"taiwan": "台灣"}, sources=[_source(section="world")])

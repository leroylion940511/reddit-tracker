import pytest
from pydantic import ValidationError

from reddit_tracker.seeds.news_sources import NewsSource, SourceRegistry, load_registry


def test_registry_loads_and_every_section_has_enabled_sources():
    registry = load_registry()
    sections = {s.section for s in registry.enabled()}
    assert sections == set(registry.sections)


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

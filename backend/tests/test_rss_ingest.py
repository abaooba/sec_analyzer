"""Tests for rss_ingest: Google-News query/URL building + article normalize/dedupe.

The feed fetch is mocked, so these are fully offline.
"""

import types

from backend.app import rss_ingest
from backend.app.rss_ingest import (
    build_google_news_rss_url,
    dedupe_articles,
    normalize_rss_entry,
    normalize_title_for_dedupe,
    search_company_rss_news,
)


def test_build_url_encodes_query_and_pins_us_english():
    url = build_google_news_rss_url("Apple AND tariffs")
    assert url.startswith("https://news.google.com/rss/search?q=")
    assert "Apple+AND+tariffs" in url  # quote_plus encodes spaces as '+'
    assert "hl=en-US&gl=US&ceid=US:en" in url


def test_normalize_rss_entry_flattens_and_falls_back():
    entry = {"title": "T", "link": "L", "updated": "2024-01-01", "summary": "S"}
    out = normalize_rss_entry(entry, "Google News RSS")
    assert out["title"] == "T"
    assert out["source"] == "Google News RSS"
    assert out["published"] == "2024-01-01"  # falls back to 'updated' when no 'published'
    assert out["raw"] is entry


def test_normalize_title_strips_publisher_and_punctuation():
    assert normalize_title_for_dedupe("Apple Raises Prices - Bloomberg") == "apple raises prices"
    assert normalize_title_for_dedupe("  Tariffs, Trade & War!  ") == "tariffs trade war"
    assert normalize_title_for_dedupe("") == ""


def test_dedupe_collapses_same_story_from_many_outlets():
    articles = [
        {"title": "Apple Raises Prices - Bloomberg"},
        {"title": "Apple Raises Prices - Reuters"},  # same story, different outlet
        {"title": "Different Headline Entirely"},
        {"title": ""},  # empty -> dropped
    ]
    deduped = dedupe_articles(articles)
    assert len(deduped) == 2
    assert deduped[0]["title"] == "Apple Raises Prices - Bloomberg"  # first one kept


def test_search_builds_boolean_query_and_dedupes(monkeypatch):
    captured = {}

    class FakeClient:
        def fetch_feed(self, url):
            captured["url"] = url
            return types.SimpleNamespace(
                entries=[
                    {"title": "Apple tariff news - Bloomberg"},
                    {"title": "Apple tariff news - CNBC"},  # duplicate story
                ]
            )

    monkeypatch.setattr(rss_ingest, "RSSClient", lambda: FakeClient())
    results = search_company_rss_news("Apple", ticker="AAPL", extra_terms=["tariffs", "china"])

    # query is ("Apple" OR "AAPL") AND (tariffs OR china), URL-encoded
    assert "%22Apple%22+OR+%22AAPL%22" in captured["url"]
    assert len(results) == 1  # the two outlets collapsed to one
    assert results[0]["source"] == "Google News RSS"

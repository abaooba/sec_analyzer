"""Tests for article_extractor (redirect-resolve + trafilatura body extraction).

httpx (via make_http_client) and trafilatura are mocked, so these are offline.
"""

import types

from backend.app import article_extractor
from backend.app.article_extractor import extract_article_text, resolve_final_url


class _FakeClient:
    def __init__(self, final_url=None, raise_on_get=False):
        self._final_url = final_url
        self._raise = raise_on_get

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def get(self, url, headers=None):
        if self._raise:
            raise RuntimeError("network down")
        return types.SimpleNamespace(url=self._final_url)


def test_resolve_final_url_follows_redirect(monkeypatch):
    monkeypatch.setattr(
        article_extractor,
        "make_http_client",
        lambda **k: _FakeClient(final_url="https://publisher.example.com/story"),
    )
    assert resolve_final_url("https://news.google.com/redirect") == (
        "https://publisher.example.com/story"
    )


def test_resolve_final_url_falls_back_to_original_on_error(monkeypatch):
    monkeypatch.setattr(
        article_extractor, "make_http_client", lambda **k: _FakeClient(raise_on_get=True)
    )
    assert resolve_final_url("https://original.example.com") == "https://original.example.com"


def test_extract_article_text_success(monkeypatch):
    monkeypatch.setattr(article_extractor, "resolve_final_url", lambda url: "https://final.example.com")
    monkeypatch.setattr(article_extractor.trafilatura, "fetch_url", lambda url: "<html>raw</html>")
    monkeypatch.setattr(article_extractor.trafilatura, "extract", lambda html: "clean body text")
    text, final_url = extract_article_text("https://x")
    assert text == "clean body text"
    assert final_url == "https://final.example.com"


def test_extract_article_text_none_when_download_empty(monkeypatch):
    monkeypatch.setattr(article_extractor, "resolve_final_url", lambda url: "https://final")
    monkeypatch.setattr(article_extractor.trafilatura, "fetch_url", lambda url: None)
    text, final_url = extract_article_text("https://x")
    assert text is None
    assert final_url == "https://final"


def test_extract_article_text_none_on_exception(monkeypatch):
    monkeypatch.setattr(article_extractor, "resolve_final_url", lambda url: "https://final")

    def boom(url):
        raise RuntimeError("trafilatura blew up")

    monkeypatch.setattr(article_extractor.trafilatura, "fetch_url", boom)
    text, final_url = extract_article_text("https://x")
    assert text is None
    assert final_url == "https://final"

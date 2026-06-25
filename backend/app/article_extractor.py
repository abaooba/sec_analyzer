"""Fetch the full body text of a news article from its URL.

A helper utility (not currently wired into the live scoring path — the
geopolitics scorer works off headline/summary text alone). `trafilatura` is a
library that strips boilerplate (nav, ads, footers) and returns just the main
article text. Google News links are redirect URLs, so we resolve to the real
destination first.
"""

import trafilatura

from .http_client import make_http_client


def resolve_final_url(url: str) -> str:
    """Follow redirects to get the publisher's real URL (Google News wraps links)."""
    try:
        with make_http_client(timeout=30.0, follow_redirects=True) as client:
            response = client.get(url, headers={"User-Agent": "Mozilla/5.0"})
            return str(response.url)
    except Exception:
        return url  # on failure, just use the original URL


def extract_article_text(url: str) -> tuple[str | None, str]:
    """Return (clean_article_text_or_None, final_url) for a given article URL."""
    final_url = resolve_final_url(url)

    try:
        downloaded = trafilatura.fetch_url(final_url)
        if not downloaded:
            return None, final_url

        text = trafilatura.extract(downloaded)  # boilerplate-stripped main text
        return text, final_url
    except Exception:
        return None, final_url
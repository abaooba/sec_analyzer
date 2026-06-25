"""Tiny RSS fetcher: download a feed URL and parse it with feedparser.

Used by rss_ingest to pull Google News results. We fetch the raw XML ourselves
with httpx (rather than letting feedparser fetch) so we control headers and
redirects, then hand the text to `feedparser.parse`.

TLS certificate verification is on by default (clients are built via
`make_http_client`); set `TLS_VERIFY=false` only behind a trusted intercepting
proxy.
"""

import feedparser

from .http_client import make_http_client


class RSSClient:
    def fetch_feed(self, feed_url: str) -> feedparser.FeedParserDict:
        """Download and parse an RSS/Atom feed into a feedparser result dict."""
        headers = {
            # Pretend to be a browser; some feeds reject unknown user-agents.
            "User-Agent": "Mozilla/5.0",
        }

        with make_http_client(timeout=30.0, follow_redirects=True) as client:
            response = client.get(feed_url, headers=headers)
            response.raise_for_status()
            return feedparser.parse(response.text)
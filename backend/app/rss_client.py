"""Tiny RSS fetcher: download a feed URL and parse it with feedparser.

Used by rss_ingest to pull Google News results. We fetch the raw XML ourselves
with httpx (rather than letting feedparser fetch) so we control headers and
redirects, then hand the text to `feedparser.parse`.

Note `verify=False` disables TLS certificate verification — convenient for a
hobby project but something you'd remove in production.
"""

import httpx
import feedparser


class RSSClient:
    def fetch_feed(self, feed_url: str) -> dict:
        """Download and parse an RSS/Atom feed into a feedparser result dict."""
        headers = {
            # Pretend to be a browser; some feeds reject unknown user-agents.
            "User-Agent": "Mozilla/5.0",
        }

        with httpx.Client(timeout=30.0, follow_redirects=True, verify=False) as client:
            response = client.get(feed_url, headers=headers)
            response.raise_for_status()
            return feedparser.parse(response.text)
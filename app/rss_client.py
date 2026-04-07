import httpx
import feedparser


class RSSClient:
    def fetch_feed(self, feed_url: str) -> dict:
        headers = {
            "User-Agent": "Mozilla/5.0",
        }

        with httpx.Client(timeout=30.0, follow_redirects=True, verify=False) as client:
            response = client.get(feed_url, headers=headers)
            response.raise_for_status()
            return feedparser.parse(response.text) 
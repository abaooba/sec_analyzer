"""Build Google News searches and normalize/dedupe the resulting articles.

Google News exposes search as an RSS feed, so we can query it without an API
key: build a search URL, fetch it via RSSClient, normalize each entry into a
flat dict, and drop duplicate headlines. The geopolitics scorer consumes the
output. This is a neat "free data source" trick — no NewsAPI key required.
"""

from urllib.parse import quote_plus
import re

from .rss_client import RSSClient


def build_google_news_rss_url(query: str) -> str:
    """Turn a search query into a Google News RSS URL (URL-encoding the query).

    The hl/gl/ceid params pin the results to US English.
    """
    encoded_query = quote_plus(query)
    return f"https://news.google.com/rss/search?q={encoded_query}&hl=en-US&gl=US&ceid=US:en"


def normalize_rss_entry(entry: dict, source_name: str) -> dict:
    """Flatten a feedparser entry into the simple shape the rest of the app uses."""
    return {
        "source": source_name,
        "title": entry.get("title"),
        "link": entry.get("link"),
        "published": entry.get("published", entry.get("updated")),
        "summary": entry.get("summary", ""),
        "raw": entry,
    }


def normalize_title_for_dedupe(title: str) -> str:
    """Canonicalize a headline so near-identical articles collapse together.

    Google News often returns the same story from many outlets with the
    publisher appended ("... - Bloomberg"). Stripping that suffix plus
    punctuation lets us treat them as one.
    """
    if not title:
        return ""

    title = title.lower().strip()

    # remove trailing publisher names like " - Bloomberg"
    title = re.sub(r"\s+-\s+[^\-]+$", "", title)

    # collapse punctuation/spacing
    title = re.sub(r"[^a-z0-9\s]", " ", title)
    title = re.sub(r"\s+", " ", title).strip()

    return title


def dedupe_articles(articles: list[dict]) -> list[dict]:
    """Keep only the first article per canonicalized title."""
    seen_titles = set()
    deduped = []

    for article in articles:
        normalized_title = normalize_title_for_dedupe(article.get("title") or "")
        if not normalized_title:
            continue

        if normalized_title in seen_titles:
            continue

        seen_titles.add(normalized_title)
        deduped.append(article)

    return deduped


def search_company_rss_news(
    company_name: str,
    ticker: str | None = None,
    extra_terms: list[str] | None = None,
) -> list[dict]:
    """Search Google News for a company, narrowed to geopolitical topic terms.

    Builds a boolean query like:
        ("Apple" OR "AAPL") AND (tariffs OR china OR "supply chain" ...)
    so we only get articles about the company *in a geopolitical context*, then
    returns the normalized, de-duplicated article list.
    """
    client = RSSClient()

    # Identity clause: company name (and ticker if provided), quoted for exactness.
    query_parts = [f'"{company_name}"']
    if ticker:
        query_parts.append(f'"{ticker}"')

    if extra_terms:
        query_parts.extend(extra_terms)

    # Use just the name/ticker for the identity OR-group...
    query = " OR ".join(query_parts[:2])
    # ...then AND it with the topic terms to focus the results.
    if extra_terms:
        query = f"({query}) AND ({' OR '.join(extra_terms)})"

    feed_url = build_google_news_rss_url(query)
    parsed = client.fetch_feed(feed_url)

    results = []
    for entry in parsed.entries:
        results.append(normalize_rss_entry(entry, "Google News RSS"))

    return dedupe_articles(results)

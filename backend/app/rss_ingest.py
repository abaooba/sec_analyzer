from urllib.parse import quote_plus
import re

from frontend.app.rss_client import RSSClient


def build_google_news_rss_url(query: str) -> str:
    encoded_query = quote_plus(query)
    return f"https://news.google.com/rss/search?q={encoded_query}&hl=en-US&gl=US&ceid=US:en"


def normalize_rss_entry(entry: dict, source_name: str) -> dict:
    return {
        "source": source_name,
        "title": entry.get("title"),
        "link": entry.get("link"),
        "published": entry.get("published", entry.get("updated")),
        "summary": entry.get("summary", ""),
        "raw": entry,
    }


def normalize_title_for_dedupe(title: str) -> str:
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
    client = RSSClient()

    query_parts = [f'"{company_name}"']
    if ticker:
        query_parts.append(f'"{ticker}"')

    if extra_terms:
        query_parts.extend(extra_terms)

    query = " OR ".join(query_parts[:2])
    if extra_terms:
        query = f"({query}) AND ({' OR '.join(extra_terms)})"

    feed_url = build_google_news_rss_url(query)
    parsed = client.fetch_feed(feed_url)

    results = []
    for entry in parsed.entries:
        results.append(normalize_rss_entry(entry, "Google News RSS"))

    return dedupe_articles(results)
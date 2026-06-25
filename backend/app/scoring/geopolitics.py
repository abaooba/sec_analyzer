"""Geopolitical-impact scoring — the most ambitious scorer.

It fuses TWO signals:
  1. EVENT signal: live news headlines about the company (via Google News RSS),
     classified into geopolitical categories (tariffs, sanctions, war, China,
     etc.). This captures what's happening *right now*.
  2. EXPOSURE signal: how much the company's own filing talks about being
     exposed to those same categories. This captures structural vulnerability.

The clever bit is the OVERLAP term: a category scores highest when current
events AND the company's disclosed exposure line up (e.g. there's tariff news
AND the filing says the company is heavily exposed to tariffs). Two keyword maps
are kept separate on purpose — GEOPOLITICAL_EVENT_KEYWORDS matches news text,
EXPOSURE_KEYWORDS matches the more measured language of filings.

Higher score = more geopolitical pressure (inverted in the final opinion).
"""

import re

from ..article_extractor import extract_article_text
from ..parse_filings import extract_latest_filing_sections, combine_section_texts
from ..rss_ingest import search_company_rss_news


# How many of the top articles to fetch full body text for. Bounded because each
# one is two network round-trips (resolve redirect + download); the rest are
# still classified on their headline + summary.
FULL_TEXT_ARTICLE_LIMIT = 5


# Patterns used to classify news articles into geopolitical event categories.
# Matched against title + summary, plus full body text when we fetched it.
GEOPOLITICAL_EVENT_KEYWORDS = {
    "tariffs_trade": [
        r"\btariff\b",
        r"\btariffs\b",
        r"trade war",
        r"trade restrictions",
        r"trade tensions",
        r"import duties",
        r"export duties",
        r"customs duties",
        r"trade barrier",
    ],
    "sanctions_export_controls": [
        r"\bsanctions\b",
        r"export controls",
        r"\bblacklist\b",
        r"entity list",
        r"restricted exports",
        r"licensing restrictions",
        r"license denial",
        r"export license",
        r"national security restrictions",
    ],
    "war_conflict": [
        r"\bwar\b",
        r"\bconflict\b",
        r"\bmilitary\b",
        r"\binvasion\b",
        r"\bmissile\b",
        r"\bhostilities\b",
        r"\battack\b",
        r"armed conflict",
        r"cross-strait",
    ],
    "supply_chain_disruption": [
        r"supply chain",
        r"\bmanufacturing\b",
        r"\bsupplier\b",
        r"\bsuppliers\b",
        r"\bshipping\b",
        r"\blogistics\b",
        r"\bdisruption\b",
        r"\bfactory\b",
        r"\bassembly\b",
        r"lead times",
        r"capacity constraints",
        r"supply constraints",
    ],
    "china_exposure": [
        r"\bchina\b",
        r"\bchinese\b",
        r"\bbeijing\b",
        r"\btaiwan\b",
        r"\btaiwanese\b",
        r"taiwan strait",
        r"export controls",
        r"semiconductor restrictions",
    ],
    "regulation_antitrust": [
        r"\bregulation\b",
        r"\bregulatory\b",
        r"\bantitrust\b",
        r"\binvestigation\b",
        r"\bcompliance\b",
        r"competition authority",
        r"government review",
        r"state aid",
    ],
    "macro_demand": [
        r"\bslump\b",
        r"\bslowdown\b",
        r"\brecession\b",
        r"\binflation\b",
        r"interest rates",
        r"consumer demand",
        r"pricing pressure",
        r"\bmargins\b",
        r"industrial demand",
        r"cyclical demand",
    ],
    "middle_east_energy_shipping": [
        r"\biran\b",
        r"\bisrael\b",
        r"\bgaza\b",
        r"\bhamas\b",
        r"\bhezbollah\b",
        r"middle east",
        r"persian gulf",
        r"strait of hormuz",
        r"red sea",
        r"\bhouthi\b",
        r"\byemen\b",
        r"oil prices",
        r"energy prices",
        r"\blng\b",
        r"crude oil",
        r"\btanker\b",
        r"shipping route",
        r"shipping disruption",
    ],
}

GEOPOLITICAL_WEIGHTS = {
    "tariffs_trade": 1.4,
    "sanctions_export_controls": 1.5,
    "war_conflict": 1.3,
    "supply_chain_disruption": 1.4,
    "china_exposure": 1.5,
    "regulation_antitrust": 1.3,
    "macro_demand": 1.1,
    "middle_east_energy_shipping": 1.5,
}

# Patterns used to measure the COMPANY'S OWN EXPOSURE in its filing text.
# Same category keys as the event map so the two signals can be overlapped.
EXPOSURE_KEYWORDS = {
    "tariffs_trade": [
        r"\btariffs\b",
        r"trade restrictions",
        r"international operations",
        r"regional economic conditions",
        r"customs duties",
        r"cross-border",
    ],
    "sanctions_export_controls": [
        r"\bsanctions\b",
        r"export controls",
        r"trade restrictions",
        r"licensing restrictions",
        r"export license",
        r"restricted jurisdictions",
    ],
    "war_conflict": [
        r"\bgeopolitical\b",
        r"\bwar\b",
        r"international operations",
        r"armed conflict",
        r"military conflict",
        r"geopolitical tensions",
    ],
    "supply_chain_disruption": [
        r"supply chain",
        r"\bsupplier\b",
        r"\bsuppliers\b",
        r"\bmanufacturing\b",
        r"\bassembly\b",
        r"\blogistics\b",
        r"\bcomponent\b",
        r"\bsemiconductor\b",
        r"\bproduction\b",
        r"lead times",
        r"capacity constraints",
    ],
    "china_exposure": [
        r"\bchina\b",
        r"\bchinese\b",
        r"\btaiwan\b",
        r"\basia\b",
        r"international operations",
        r"sales outside the u.s.",
        r"supplier facilities",
        r"manufacturing and assembly sites",
        r"taiwan strait",
    ],
    "regulation_antitrust": [
        r"\bregulation\b",
        r"\bregulatory\b",
        r"\bcompliance\b",
        r"\bgovernment\b",
        r"\bantitrust\b",
        r"export controls",
        r"competition authority",
        r"licensing restrictions",
    ],
    "macro_demand": [
        r"\binflation\b",
        r"interest rates",
        r"consumer confidence",
        r"\bspending\b",
        r"economic conditions",
        r"\brecession\b",
        r"\bcyclical\b",
        r"\bdemand\b",
        r"pricing pressure",
        r"foreign exchange",
    ],
    "middle_east_energy_shipping": [
        r"oil prices",
        r"energy prices",
        r"\bshipping\b",
        r"\blogistics\b",
        r"supply chain",
        r"international operations",
        r"regional economic conditions",
        r"\binflation\b",
        r"currency fluctuations",
    ],
}


def normalize_text(text: str) -> str:
    if not text:
        return ""
    return text.lower()


def count_keyword_matches(pattern: str, text: str) -> int:
    return len(re.findall(pattern, text))


def matches_any_pattern(text: str, patterns: list[str]) -> bool:
    """True if ANY pattern hits — used to classify a single news article."""
    return any(re.search(pattern, text) for pattern in patterns)


def soften_count(count: int) -> int:
    if count <= 0:
        return 0
    if count <= 2:
        return 1
    if count <= 5:
        return 2
    return 3


def count_keywords(text: str, keyword_map: dict) -> dict:
    normalized = normalize_text(text)
    results = {}

    for category, keywords in keyword_map.items():
        keyword_hits = {}
        raw_total = 0
        softened_total = 0

        for keyword in keywords:
            count = count_keyword_matches(keyword, normalized)
            if count > 0:
                keyword_hits[keyword] = count
                raw_total += count
                softened_total += soften_count(count)

        results[category] = {
            "raw_total_hits": raw_total,
            "softened_total_hits": softened_total,
            "keyword_hits": keyword_hits,
        }

    return results


def build_article_text(article: dict) -> str:
    """Combine an article's title + summary (+ full body, if fetched) into one
    searchable blob. The richer the text, the better the category classification."""
    title = article.get("title") or ""
    summary = article.get("summary") or ""
    full_text = article.get("full_text") or ""  # present only for enriched articles
    return f"{title} {summary} {full_text}"


def enrich_articles_with_full_text(
    articles: list[dict],
    limit: int = FULL_TEXT_ARTICLE_LIMIT,
) -> list[dict]:
    """Fetch and attach real article body text for up to `limit` articles.

    Mutates each enriched article in place, adding `full_text` (the cleaned
    body) and `resolved_url` (the publisher URL behind the Google News redirect)
    via article_extractor. Best-effort: extraction failures are skipped silently
    so a dead link never breaks scoring, and we stop once `limit` succeed to keep
    the network cost bounded.
    """
    enriched = 0

    for article in articles:
        if enriched >= limit:
            break

        link = article.get("link")
        if not link:
            continue

        text, final_url = extract_article_text(link)
        if text:
            article["full_text"] = text
            article["resolved_url"] = final_url
            enriched += 1

    return articles


def classify_articles(articles: list[dict]) -> dict:
    """Tally how many news articles fall into each geopolitical category, and
    keep up to 5 article references per category as evidence for the report."""
    category_articles: dict[str, list[dict]] = {category: [] for category in GEOPOLITICAL_EVENT_KEYWORDS.keys()}
    category_counts = {category: 0 for category in GEOPOLITICAL_EVENT_KEYWORDS.keys()}

    for article in articles:
        text = normalize_text(build_article_text(article))

        for category, keywords in GEOPOLITICAL_EVENT_KEYWORDS.items():
            if matches_any_pattern(text, keywords):
                category_counts[category] += 1

                if len(category_articles[category]) < 5:
                    category_articles[category].append(
                        {
                            "title": article.get("title"),
                            "link": article.get("link"),
                            "source": article.get("source"),
                            "published": article.get("published"),
                        }
                    )

    return {
        "category_counts": category_counts,
        "category_articles": category_articles,
    }


def extract_company_exposure(cik: str) -> dict:
    """Measure the company's structural exposure by keyword-scanning its filing."""
    sections = extract_latest_filing_sections(
        cik,
        preferred_forms=("20-F", "10-K", "40-F", "10-Q", "6-K", "8-K"),
    )

    filing_text = combine_section_texts(
        sections,
        "risk_factors",
        "mdna",
        "business",
        min_chars=300,
    ).strip()

    if not filing_text:
        filing_text = sections.get("full_text") or ""

    return {
        "filing_form_used": sections.get("form"),
        "filing_date_used": sections.get("filing_date"),
        "keyword_results": count_keywords(filing_text, EXPOSURE_KEYWORDS),
    }


def score_geopolitical_impact(
    cik: str,
    company_name: str,
    ticker: str | None = None,
    extra_terms: list[str] | None = None,
) -> dict:
    """Top-level: combine live news + filing exposure into a geopolitical score."""
    # Pull recent news; news fetching is best-effort, so failures -> no articles
    # (the score then leans entirely on filing exposure rather than crashing).
    try:
        articles = search_company_rss_news(
            company_name=company_name,
            ticker=ticker,
            extra_terms=extra_terms
            or [
                "tariffs",
                "china",
                "taiwan",
                "supply chain",
                "regulation",
                "antitrust",
                "iran",
                "middle east",
                "strait of hormuz",
                "red sea",
                "oil prices",
                "shipping disruption",
                "export controls",
            ],
        )
        # Pull full body text for the top articles so classification sees more
        # than just the headline. Also best-effort within the same guard.
        articles = enrich_articles_with_full_text(articles)
    except Exception:
        articles = []

    article_results = classify_articles(articles)              # the EVENT signal
    exposure_bundle = extract_company_exposure(cik)            # the EXPOSURE signal
    exposure_results = exposure_bundle["keyword_results"]

    category_scores = {}
    total_score = 0

    # Per-category fusion of the two signals.
    for category in GEOPOLITICAL_EVENT_KEYWORDS.keys():
        event_hits = article_results["category_counts"].get(category, 0)
        # Cap filing exposure at 4 so a verbose filing can't run away with it.
        exposure_hits = min(
            exposure_results.get(category, {}).get("softened_total_hits", 0),
            4,
        )

        event_signal = soften_count(event_hits)
        # Overlap = both signals present; this is the high-conviction term.
        overlap_signal = min(event_signal, exposure_hits)
        weighted_score = (
            event_signal * 0.8       # current events matter
            + exposure_hits * 0.9    # structural exposure matters a bit more
            + overlap_signal * 1.2   # but the two TOGETHER matter most
        ) * GEOPOLITICAL_WEIGHTS.get(category, 1.0)
        category_score = min(round(weighted_score, 2), 15)

        category_scores[category] = category_score
        total_score += category_score

    total_score = min(round(total_score, 2), 100)

    return {
        "total_geopolitical_score": total_score,
        "category_scores": category_scores,
        "news_category_counts": article_results["category_counts"],
        "news_evidence": article_results["category_articles"],
        "filing_exposure": exposure_results,
        "filing_form_used": exposure_bundle["filing_form_used"],
        "filing_date_used": exposure_bundle["filing_date_used"],
        "article_count": len(articles),
        # How many articles we successfully pulled full body text for.
        "full_text_article_count": sum(1 for a in articles if a.get("full_text")),
    }

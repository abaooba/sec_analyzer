"""Resolve a human-typed company name (and/or ticker) into a CIK.

The user types "Apple" or "AAPL"; the rest of the pipeline needs the company's
CIK. The SEC publishes a single JSON file mapping every ticker to its
{title, ticker, cik}. We download that file and do fuzzy-ish matching in
Python, with a clear precedence order so the best match wins.
"""

from .config import settings
from .http_client import make_http_client

# Official SEC-published ticker -> CIK directory (one big JSON object).
SEC_COMPANY_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"


def load_company_tickers() -> dict:
    """Download the full SEC ticker directory as a dict."""
    headers = {
        "User-Agent": settings.sec_user_agent,
        "Accept-Encoding": "gzip, deflate",
    }

    with make_http_client(headers=headers, timeout=30.0, follow_redirects=True) as client:
        response = client.get(SEC_COMPANY_TICKERS_URL)
        response.raise_for_status()
        return response.json()


def normalize_name(name: str) -> str:
    """Lowercase + collapse internal whitespace so name comparisons are robust."""
    return " ".join(name.lower().strip().split())


def find_company_match(company_name: str, ticker: str | None = None) -> dict | None:
    """Find the best company record for the given name (optionally narrowed by ticker).

    Returns {"company_name", "ticker", "cik"} or None. Matching precedence:
      1. ticker match (preferring one whose name also matches the typed name)
      2. exact normalized-name match
      3. partial name match (typed name is a substring of the official title)
    """
    data = load_company_tickers()

    normalized_name = normalize_name(company_name)
    normalized_ticker = ticker.upper().strip() if ticker else None

    # Collect candidates into three buckets as we scan the whole directory once.
    exact_name_matches = []
    partial_name_matches = []
    ticker_matches = []

    for _, company in data.items():
        title = company.get("title", "")
        company_ticker = company.get("ticker", "")
        cik_str = str(company.get("cik_str", "")).zfill(10)  # normalize to 10 digits

        normalized_title = normalize_name(title)

        record = {
            "company_name": title,
            "ticker": company_ticker,
            "cik": cik_str,
        }

        # Bucket this company by how it matches the user input.
        if normalized_ticker and company_ticker.upper() == normalized_ticker:
            ticker_matches.append(record)

        if normalized_title == normalized_name:
            exact_name_matches.append(record)
        elif normalized_name in normalized_title:
            partial_name_matches.append(record)

    # A ticker is the strongest signal, so resolve it first.
    if normalized_ticker and ticker_matches:
        if company_name:
            # Among ticker matches, prefer one whose name also exactly matches...
            for match in ticker_matches:
                if normalize_name(match["company_name"]) == normalized_name:
                    return match

            # ...then one whose name contains the typed name.
            for match in ticker_matches:
                if normalized_name in normalize_name(match["company_name"]):
                    return match

        # Otherwise just take the first ticker hit.
        return ticker_matches[0]

    # No ticker (or no ticker match): fall back to name matching.
    if exact_name_matches:
        return exact_name_matches[0]

    if partial_name_matches:
        return partial_name_matches[0]

    return None  # nothing matched

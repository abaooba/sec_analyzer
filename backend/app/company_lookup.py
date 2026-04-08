import httpx
from frontend.app.config import settings

SEC_COMPANY_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"


def load_company_tickers() -> dict:
    headers = {
        "User-Agent": settings.sec_user_agent,
        "Accept-Encoding": "gzip, deflate",
    }

    with httpx.Client(headers=headers, timeout=30.0, follow_redirects=True) as client:
        response = client.get(SEC_COMPANY_TICKERS_URL)
        response.raise_for_status()
        return response.json()


def normalize_name(name: str) -> str:
    return " ".join(name.lower().strip().split())


def find_company_match(company_name: str, ticker: str | None = None) -> dict | None:
    data = load_company_tickers()

    normalized_name = normalize_name(company_name)
    normalized_ticker = ticker.upper().strip() if ticker else None

    exact_name_matches = []
    partial_name_matches = []
    ticker_matches = []

    for _, company in data.items():
        title = company.get("title", "")
        company_ticker = company.get("ticker", "")
        cik_str = str(company.get("cik_str", "")).zfill(10)

        normalized_title = normalize_name(title)

        record = {
            "company_name": title,
            "ticker": company_ticker,
            "cik": cik_str,
        }

        if normalized_ticker and company_ticker.upper() == normalized_ticker:
            ticker_matches.append(record)

        if normalized_title == normalized_name:
            exact_name_matches.append(record)
        elif normalized_name in normalized_title:
            partial_name_matches.append(record)

    if normalized_ticker and ticker_matches:
        if company_name:
            for match in ticker_matches:
                if normalize_name(match["company_name"]) == normalized_name:
                    return match

            for match in ticker_matches:
                if normalized_name in normalize_name(match["company_name"]):
                    return match

        return ticker_matches[0]

    if exact_name_matches:
        return exact_name_matches[0]

    if partial_name_matches:
        return partial_name_matches[0]

    return None
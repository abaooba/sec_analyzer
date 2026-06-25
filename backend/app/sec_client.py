"""Thin HTTP wrapper around the SEC EDGAR REST APIs.

The SEC exposes two relevant hosts:
- data.sec.gov   — JSON APIs (the company's submission history, and XBRL facts)
- www.sec.gov/Archives — the raw filing documents (HTML)

Every request carries the descriptive User-Agent the SEC requires; without it
you get 403s. We use `httpx` (a modern requests-style HTTP client) and open a
fresh short-lived client per call for simplicity.

All SEC requests pass through `_throttle()`, a process-wide rate limiter tied to
`settings.max_requests_per_second`, so the ingest download loop stays under the
SEC's fair-access limit instead of bursting and getting throttled/blocked.
"""

import threading
import time

import httpx

from .config import settings

BASE_DATA_URL = "https://data.sec.gov"
BASE_ARCHIVES_URL = "https://www.sec.gov/Archives/edgar/data"

# Process-wide throttle state. A lock makes it safe if the API serves requests
# on multiple threads; the timestamp records when the last SEC call went out.
_throttle_lock = threading.Lock()
_last_request_at = 0.0


def _throttle() -> None:
    """Block just long enough to honor settings.max_requests_per_second.

    Spaces consecutive SEC calls by at least 1 / max_requests_per_second
    seconds. Shared across every SECClient instance so the limit is global, not
    per-object — the download loop in ingest.py is the main beneficiary.
    """
    global _last_request_at
    min_interval = 1.0 / max(settings.max_requests_per_second, 1)

    with _throttle_lock:
        wait = _last_request_at + min_interval - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        _last_request_at = time.monotonic()


class SECClient:
    def __init__(self):
        # Headers reused on every request. gzip/deflate lets the SEC compress
        # the (often large) JSON/HTML responses to save bandwidth.
        self.headers = {
            "User-Agent": settings.sec_user_agent,
            "Accept-Encoding": "gzip, deflate",
        }

    def normalize_cik(self, cik: str) -> str:
        # SEC endpoints expect the CIK as exactly 10 digits, zero-padded.
        return str(cik).zfill(10)

    def get_submissions(self, cik: str) -> dict:
        """Fetch a company's filing history (the 'submissions' JSON).

        Returns metadata about the company plus parallel arrays of its recent
        filings (form types, accession numbers, dates, primary docs).
        """
        cik = self.normalize_cik(cik)
        url = f"{BASE_DATA_URL}/submissions/CIK{cik}.json"

        _throttle()  # respect the SEC rate limit before every call
        with httpx.Client(headers=self.headers, timeout=settings.request_timeout) as client:
            response = client.get(url)
            response.raise_for_status()  # turn any 4xx/5xx into an exception
            return response.json()

    def get_company_facts(self, cik: str) -> dict:
        """Fetch all XBRL 'company facts' (structured financial data) for a CIK."""
        cik = self.normalize_cik(cik)
        url = f"{BASE_DATA_URL}/api/xbrl/companyfacts/CIK{cik}.json"

        _throttle()  # respect the SEC rate limit before every call
        with httpx.Client(headers=self.headers, timeout=settings.request_timeout) as client:
            response = client.get(url)
            response.raise_for_status()
            return response.json()

    def build_filing_url(self, cik: str, accession_no: str, primary_doc: str) -> str:
        """Construct the public archive URL for an individual filing document.

        Quirk of EDGAR's archive layout: the CIK in the path has NO leading
        zeros, and the accession number has its dashes stripped.
        e.g. .../edgar/data/320193/000032019323000106/aapl-20230930.htm
        """
        cik_no_leading_zeros = str(int(cik))
        accession_no_no_dashes = accession_no.replace("-", "")
        return f"{BASE_ARCHIVES_URL}/{cik_no_leading_zeros}/{accession_no_no_dashes}/{primary_doc}"

    def download_filing_html(self, filing_url: str) -> str:
        """Download the raw HTML of a single filing document."""
        _throttle()  # the ingest loop calls this repeatedly — throttle each one
        with httpx.Client(headers=self.headers, timeout=settings.request_timeout) as client:
            response = client.get(filing_url)
            response.raise_for_status()
            return response.text

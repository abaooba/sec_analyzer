import httpx
from frontend.app.config import settings

BASE_DATA_URL = "https://data.sec.gov"
BASE_ARCHIVES_URL = "https://www.sec.gov/Archives/edgar/data"


class SECClient:
    def __init__(self):
        self.headers = {
            "User-Agent": settings.sec_user_agent,
            "Accept-Encoding": "gzip, deflate",
        }

    def normalize_cik(self, cik: str) -> str:
        return str(cik).zfill(10)

    def get_submissions(self, cik: str) -> dict:
        cik = self.normalize_cik(cik)
        url = f"{BASE_DATA_URL}/submissions/CIK{cik}.json"

        with httpx.Client(headers=self.headers, timeout=settings.request_timeout) as client:
            response = client.get(url)
            response.raise_for_status()
            return response.json()

    def get_company_facts(self, cik: str) -> dict:
        cik = self.normalize_cik(cik)
        url = f"{BASE_DATA_URL}/api/xbrl/companyfacts/CIK{cik}.json"

        with httpx.Client(headers=self.headers, timeout=settings.request_timeout) as client:
            response = client.get(url)
            response.raise_for_status()
            return response.json()

    def build_filing_url(self, cik: str, accession_no: str, primary_doc: str) -> str:
        cik_no_leading_zeros = str(int(cik))
        accession_no_no_dashes = accession_no.replace("-", "")
        return f"{BASE_ARCHIVES_URL}/{cik_no_leading_zeros}/{accession_no_no_dashes}/{primary_doc}"
    
    def download_filing_html(self, filing_url: str) -> str:
        with httpx.Client(headers=self.headers, timeout=settings.request_timeout) as client:
            response = client.get(filing_url)
            response.raise_for_status()
            return response.text
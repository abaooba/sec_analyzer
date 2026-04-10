import json
import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.app.db import init_db
from backend.app.ingest import ingest_company, delete_local_filings_for_company
from backend.app.fundamentals import ingest_company_facts
from backend.app.opinion import build_full_opinion


def main():
    cik = input("Enter company CIK: ").strip()
    company_name = input("Enter company name: ").strip()
    ticker = input("Enter ticker: ").strip().upper()

    normalized_cik = cik.zfill(10)

    init_db()

    try:
        ingest_company(normalized_cik)
        ingest_company_facts(normalized_cik)

        result = build_full_opinion(normalized_cik, company_name, ticker)

        print(json.dumps(result, indent=2))

    finally:
        delete_local_filings_for_company(normalized_cik)


if __name__ == "__main__":
    main()

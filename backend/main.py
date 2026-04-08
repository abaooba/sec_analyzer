from app.db import init_db
from app.ingest import ingest_company, delete_local_filings_for_company
from app.fundamentals import ingest_company_facts
from app.opinion import build_full_opinion


def main():
    cik = input("Enter company CIK: ").strip()
    company_name = input("Enter company name: ").strip()
    ticker = input("Enter ticker: ").strip().upper()

    init_db()

    try:
        ingest_company(cik)
        ingest_company_facts(cik, ticker)
        build_full_opinion(cik, company_name, ticker)
    finally:
        delete_local_filings_for_company(cik)


if __name__ == "__main__":
    main()
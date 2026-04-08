from pathlib import Path

from sqlalchemy import select

from app.config import settings
from app.db import SessionLocal
from app.models import Company, Filing
from app.sec_client import SECClient


TARGET_FORMS = {"10-K", "10-Q", "8-K", "20-F", "6-K", "40-F"}

FORM_LIMITS = {
    "10-K": 3,
    "10-Q": 6,
    "8-K": 25,
    "20-F": 3,
    "6-K": 25,
    "40-F": 3,
}


def ingest_company(cik: str):
    client = SECClient()
    submissions = client.get_submissions(cik)

    company_cik = str(submissions["cik"]).zfill(10)
    ticker_list = submissions.get("tickers", [])
    ticker = ticker_list[0] if ticker_list else ""

    recent = submissions["filings"]["recent"]
    forms = recent["form"]
    accession_numbers = recent["accessionNumber"]
    filing_dates = recent["filingDate"]
    primary_docs = recent["primaryDocument"]

    Path(settings.raw_filings_dir).mkdir(parents=True, exist_ok=True)

    print(f"Ingesting company: {submissions['name']} ({company_cik})")
    print(f"Ticker: {ticker}")
    print("Starting filing scan...")

    with SessionLocal() as session:
        existing_company = session.get(Company, company_cik)

        if existing_company is None:
            company = Company(
                cik=company_cik,
                ticker=ticker,
                name=submissions["name"],
            )
            session.add(company)
            print("Added new company to database.")
        else:
            existing_company.ticker = ticker
            existing_company.name = submissions["name"]
            print("Company already exists in database. Metadata refreshed.")

        processed_count = 0
        downloaded_count = 0
        skipped_count = 0
        updated_count = 0
        failed_count = 0

        form_counts = {form: 0 for form in TARGET_FORMS}

        for form, accession_no, filing_date, primary_doc in zip(
            forms, accession_numbers, filing_dates, primary_docs
        ):
            if form not in TARGET_FORMS:
                continue

            if form_counts[form] >= FORM_LIMITS[form]:
                continue

            form_counts[form] += 1
            processed_count += 1

            print(f"\nProcessing {form} | {filing_date} | {primary_doc}")
            filing_url = client.build_filing_url(company_cik, accession_no, primary_doc)

            stmt = select(Filing).where(
                Filing.cik == company_cik,
                Filing.accession_no == accession_no,
            )
            existing_filing = session.execute(stmt).scalar_one_or_none()

            if existing_filing is not None:
                print("Filing already exists in database.")

                changed = False

                if not existing_filing.filing_url:
                    existing_filing.filing_url = filing_url
                    changed = True
                    print(f"Updated missing filing_url: {filing_url}")

                if not existing_filing.local_path:
                    try:
                        print(f"Downloading missing filing HTML from: {filing_url}")
                        html = client.download_filing_html(filing_url)

                        local_filename = f"{company_cik}_{accession_no}_{primary_doc}"
                        local_path = Path(settings.raw_filings_dir) / local_filename
                        local_path.write_text(html, encoding="utf-8")

                        existing_filing.local_path = str(local_path)
                        changed = True
                        downloaded_count += 1
                        print(f"Saved missing local file to: {local_path}")
                    except Exception as e:
                        failed_count += 1
                        print(f"Failed to download existing filing: {e}")
                else:
                    print(f"Local file already exists: {existing_filing.local_path}")

                if changed:
                    updated_count += 1
                else:
                    skipped_count += 1

                continue

            try:
                print(f"Downloading: {filing_url}")
                html = client.download_filing_html(filing_url)

                local_filename = f"{company_cik}_{accession_no}_{primary_doc}"
                local_path = Path(settings.raw_filings_dir) / local_filename
                local_path.write_text(html, encoding="utf-8")

                filing = Filing(
                    cik=company_cik,
                    accession_no=accession_no,
                    form=form,
                    filing_date=filing_date,
                    primary_doc=primary_doc,
                    filing_url=filing_url,
                    local_path=str(local_path),
                )
                session.add(filing)

                downloaded_count += 1
                print(f"Saved to: {local_path}")

            except Exception as e:
                failed_count += 1
                print(f"Failed to process filing {accession_no}: {e}")

        session.commit()

        print("\nIngestion complete.")
        print(f"Target filings processed: {processed_count}")
        print(f"New filings downloaded: {downloaded_count}")
        print(f"Existing filings skipped: {skipped_count}")
        print(f"Existing filings updated: {updated_count}")
        print(f"Failed filings: {failed_count}")


def delete_local_filings_for_company(cik: str):
    company_cik = str(cik).zfill(10)

    with SessionLocal() as session:
        stmt = select(Filing).where(Filing.cik == company_cik)
        filings = session.execute(stmt).scalars().all()

        deleted_count = 0
        missing_count = 0
        failed_count = 0

        for filing in filings:
            if not filing.local_path:
                continue

            path = Path(filing.local_path)

            try:
                if path.exists() and path.is_file():
                    path.unlink()
                    deleted_count += 1
                    print(f"Deleted local filing: {path}")
                else:
                    missing_count += 1
                    print(f"File already missing: {path}")

                filing.local_path = None

            except Exception as e:
                failed_count += 1
                print(f"Could not delete {path}: {e}")

        session.commit()

        print("\nLocal filing cleanup complete.")
        print(f"Deleted files: {deleted_count}")
        print(f"Already missing: {missing_count}")
        print(f"Delete failures: {failed_count}")
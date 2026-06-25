"""Download SEC filing documents and record them in the DB.

`ingest_company` is the first heavy step of the pipeline: given a CIK it pulls
the company's submission history, selects a capped number of each interesting
form type, downloads the primary HTML document for each, caches it on disk, and
upserts a Filing row. `delete_local_filings_for_company` is the cleanup step run
in a `finally:` block so we don't leave large HTML files lying around between
runs (the DB rows are kept, just the on-disk cache is cleared).
"""

from pathlib import Path

from sqlalchemy import select

from .config import resolve_storage_path, settings
from .db import SessionLocal
from .models import Company, Filing
from .sec_client import SECClient


# The filing types we care about. 10-K/10-Q/8-K are US domestic; 20-F/6-K/40-F
# are the foreign-issuer equivalents (annual / interim / Canadian).
TARGET_FORMS = {"10-K", "10-Q", "8-K", "20-F", "6-K", "40-F"}

# Cap how many of each form we ingest so we don't download a company's entire
# multi-decade history — just enough recent ones for analysis & YoY comparison.
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

    # The SEC returns recent filings as parallel arrays (column-oriented): the
    # i-th filing is forms[i] + accession_numbers[i] + filing_dates[i] + ...
    recent = submissions["filings"]["recent"]
    forms = recent["form"]
    accession_numbers = recent["accessionNumber"]
    filing_dates = recent["filingDate"]
    primary_docs = recent["primaryDocument"]

    # Ensure the on-disk cache directory exists before we start writing files.
    Path(settings.raw_filings_dir).mkdir(parents=True, exist_ok=True)

    print(f"Ingesting company: {submissions['name']} ({company_cik})")
    print(f"Ticker: {ticker}")
    print("Starting filing scan...")

    # One session = one transaction for the whole ingest; committed at the end.
    with SessionLocal() as session:
        # Upsert the Company row (insert if new, otherwise refresh its metadata).
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

        # Counters purely for the end-of-run summary printout.
        processed_count = 0
        downloaded_count = 0
        skipped_count = 0
        updated_count = 0
        failed_count = 0

        # Track how many of each form we've taken so we can stop at FORM_LIMITS.
        form_counts = {form: 0 for form in TARGET_FORMS}

        # Walk the parallel arrays together. They're newest-first, so the first
        # N of each form type are the most recent — exactly what we want.
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

            # Have we already recorded this exact filing (by accession number)?
            stmt = select(Filing).where(
                Filing.cik == company_cik,
                Filing.accession_no == accession_no,
            )
            existing_filing = session.execute(stmt).scalar_one_or_none()

            if existing_filing is not None:
                # --- Path A: filing row exists; backfill URL / re-download if needed ---
                print("Filing already exists in database.")

                changed = False
                resolved_existing_path = None
                if existing_filing.local_path:
                    resolved_existing_path = resolve_storage_path(existing_filing.local_path)

                if not existing_filing.filing_url:
                    existing_filing.filing_url = filing_url
                    changed = True
                    print(f"Updated missing filing_url: {filing_url}")

                # Re-download if we have no local copy or the cached file is gone
                # (e.g. it was cleaned up after a previous run).
                if not existing_filing.local_path or not resolved_existing_path or not resolved_existing_path.exists():
                    try:
                        print(f"Downloading filing HTML from: {filing_url}")
                        html = client.download_filing_html(filing_url)

                        local_filename = f"{company_cik}_{accession_no}_{primary_doc}"
                        local_path = Path(settings.raw_filings_dir) / local_filename
                        local_path.write_text(html, encoding="utf-8")

                        existing_filing.local_path = str(local_path)
                        changed = True
                        downloaded_count += 1
                        print(f"Saved local file to: {local_path}")
                    except Exception as e:
                        failed_count += 1
                        print(f"Failed to download existing filing: {e}")
                else:
                    print(f"Local file already exists: {resolved_existing_path}")

                if changed:
                    updated_count += 1
                else:
                    skipped_count += 1

                continue

            # --- Path B: brand-new filing; download it and insert a fresh row ---
            try:
                print(f"Downloading: {filing_url}")
                html = client.download_filing_html(filing_url)

                # Cache filename encodes cik + accession + doc so it's unique.
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
                # One bad filing shouldn't abort the whole ingest.
                failed_count += 1
                print(f"Failed to process filing {accession_no}: {e}")

        session.commit()  # persist company + all filing rows atomically

        print("\nIngestion complete.")
        print(f"Target filings processed: {processed_count}")
        print(f"New filings downloaded: {downloaded_count}")
        print(f"Existing filings skipped: {skipped_count}")
        print(f"Existing filings updated: {updated_count}")
        print(f"Failed filings: {failed_count}")


def delete_local_filings_for_company(cik: str):
    """Delete the cached HTML files for a company and blank their local_path.

    Run in a `finally:` after analysis so each request cleans up its own large
    on-disk artifacts. The Filing DB rows survive (with local_path="") as a
    record of what was seen; only the bytes on disk are removed.
    """
    company_cik = str(cik).zfill(10)

    with SessionLocal() as session:
        stmt = select(Filing).where(Filing.cik == company_cik)
        filings = session.execute(stmt).scalars().all()

        deleted_count = 0
        missing_count = 0
        failed_count = 0

        for filing in filings:
            if not filing.local_path:
                continue  # nothing cached for this row

            path = Path(filing.local_path)
            if filing.local_path:
                # Resolve relative paths the same way they were stored.
                path = resolve_storage_path(filing.local_path)

            try:
                if path.exists() and path.is_file():
                    path.unlink()  # actually delete the file
                    deleted_count += 1
                    print(f"Deleted local filing: {path}")
                else:
                    missing_count += 1
                    print(f"File already missing: {path}")

                filing.local_path = ""  # mark as no-longer-cached in the DB

            except Exception as e:
                failed_count += 1
                print(f"Could not delete {path}: {e}")

        session.commit()

        print("\nLocal filing cleanup complete.")
        print(f"Deleted files: {deleted_count}")
        print(f"Already missing: {missing_count}")
        print(f"Delete failures: {failed_count}")

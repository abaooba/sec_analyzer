"""SQLAlchemy ORM models — the database schema as Python classes.

These three tables are the app's persistence layer. `init_db()` (in db.py)
calls `Base.metadata.create_all()` to materialize them in SQLite. Using the
modern SQLAlchemy 2.0 typed style: `Mapped[...]` annotations + `mapped_column`.

Note the CIK is stored as a 10-char zero-padded *string*, not an int, because
the leading zeros are significant in SEC URLs (e.g. CIK 320193 -> "0000320193").
"""

from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy import String, Integer, Float, Text


class Base(DeclarativeBase):
    """The declarative base all models inherit from; holds the shared metadata."""
    pass


class Company(Base):
    """One row per company we've looked up. Keyed by the zero-padded CIK."""
    __tablename__ = "companies"

    cik: Mapped[str] = mapped_column(String(10), primary_key=True)  # SEC Central Index Key
    ticker: Mapped[str] = mapped_column(String(16), index=True)
    name: Mapped[str] = mapped_column(String(255))


class Filing(Base):
    """One row per downloaded SEC filing (10-K, 10-Q, 8-K, 20-F, ...).

    `accession_no` is the SEC's unique id for a submission. `local_path` points
    to the cached HTML on disk and is blanked out after cleanup, while the row
    itself is kept as a lightweight record of what we've seen.
    """
    __tablename__ = "filings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    cik: Mapped[str] = mapped_column(String(10), index=True)
    accession_no: Mapped[str] = mapped_column(String(32), index=True)
    form: Mapped[str] = mapped_column(String(16), index=True)  # form type, e.g. "10-K"
    filing_date: Mapped[str] = mapped_column(String(16))       # ISO date string "YYYY-MM-DD"
    primary_doc: Mapped[str] = mapped_column(String(255))      # main document filename
    filing_url: Mapped[str] = mapped_column(Text)              # full EDGAR archive URL
    local_path: Mapped[str] = mapped_column(Text, default="")  # cached file path ("" once deleted)


class CompanyFact(Base):
    """One row per XBRL financial data point pulled from the SEC companyfacts API.

    XBRL is the structured-financial-data standard the SEC mandates. A single
    "fact" is a tagged number for a period — e.g. tag=Revenues, unit=USD,
    fiscal_year=2023, value=383285000000. The combination of
    (cik, taxonomy, tag, unit, fy, fp, form, filed, end_date) is what we treat
    as unique to avoid inserting duplicates on re-ingest.
    """
    __tablename__ = "company_facts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    cik: Mapped[str] = mapped_column(String(10), index=True)
    taxonomy: Mapped[str] = mapped_column(String(64), index=True)   # "us-gaap" or "ifrs-full"
    tag: Mapped[str] = mapped_column(String(128), index=True)       # the XBRL concept name
    unit: Mapped[str] = mapped_column(String(32))                   # "USD", "shares", etc.
    fiscal_year: Mapped[int] = mapped_column(Integer, index=True)
    fiscal_period: Mapped[str] = mapped_column(String(8))           # "FY", "Q1", ...
    form: Mapped[str] = mapped_column(String(16))
    filed: Mapped[str] = mapped_column(String(16))                  # date the filing was filed
    end_date: Mapped[str] = mapped_column(String(16))              # period the value covers
    value: Mapped[float] = mapped_column(Float)
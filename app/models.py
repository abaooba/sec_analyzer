from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy import String, Integer, Float, Text


class Base(DeclarativeBase):
    pass


class Company(Base):
    __tablename__ = "companies"

    cik: Mapped[str] = mapped_column(String(10), primary_key=True)
    ticker: Mapped[str] = mapped_column(String(16), index=True)
    name: Mapped[str] = mapped_column(String(255))


class Filing(Base):
    __tablename__ = "filings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    cik: Mapped[str] = mapped_column(String(10), index=True)
    accession_no: Mapped[str] = mapped_column(String(32), index=True)
    form: Mapped[str] = mapped_column(String(16), index=True)
    filing_date: Mapped[str] = mapped_column(String(16))
    primary_doc: Mapped[str] = mapped_column(String(255))
    filing_url: Mapped[str] = mapped_column(Text)
    local_path: Mapped[str] = mapped_column(Text, default="")


class CompanyFact(Base):
    __tablename__ = "company_facts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    cik: Mapped[str] = mapped_column(String(10), index=True)
    taxonomy: Mapped[str] = mapped_column(String(64), index=True)
    tag: Mapped[str] = mapped_column(String(128), index=True)
    unit: Mapped[str] = mapped_column(String(32))
    fiscal_year: Mapped[int] = mapped_column(Integer, index=True)
    fiscal_period: Mapped[str] = mapped_column(String(8))
    form: Mapped[str] = mapped_column(String(16))
    filed: Mapped[str] = mapped_column(String(16))
    end_date: Mapped[str] = mapped_column(String(16))
    value: Mapped[float] = mapped_column(Float)
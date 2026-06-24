"""Shared pytest fixtures.

The only non-trivial piece here is an isolated in-memory database: several
modules (`metrics`, `parse_filings`) read via the shared `SessionLocal` bound to
the real `sec_analyzer.db`. Tests must never touch that, so we spin up a fresh
in-memory SQLite with the app's schema and monkeypatch `SessionLocal` to point at
it. `StaticPool` keeps a single underlying connection alive so the in-memory DB
persists across the multiple `SessionLocal()` calls a single test makes.
"""

from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app.models import Base

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def in_memory_sessionmaker():
    """A fresh, isolated in-memory SQLite DB with the app's tables created."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine, future=True)
    try:
        yield TestSession
    finally:
        engine.dispose()


@pytest.fixture
def patch_metrics_db(monkeypatch, in_memory_sessionmaker):
    """Repoint `metrics.SessionLocal` at the isolated in-memory DB for a test."""
    monkeypatch.setattr("backend.app.metrics.SessionLocal", in_memory_sessionmaker)
    return in_memory_sessionmaker


@pytest.fixture
def patch_parse_filings_db(monkeypatch, in_memory_sessionmaker):
    """Repoint `parse_filings.SessionLocal` at the isolated in-memory DB."""
    monkeypatch.setattr("backend.app.parse_filings.SessionLocal", in_memory_sessionmaker)
    return in_memory_sessionmaker


@pytest.fixture
def sample_10k_html():
    """Raw HTML of the synthetic 10-K fixture (TOC + Business/Risk/MD&A)."""
    return (FIXTURES_DIR / "sample_10k.html").read_text(encoding="utf-8")

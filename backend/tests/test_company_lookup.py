"""Tests for company name/ticker -> CIK matching (company_lookup).

The SEC ticker directory download is mocked, so these are fully offline and just
exercise the matching precedence: ticker > exact name > partial name.
"""

from backend.app import company_lookup
from backend.app.company_lookup import find_company_match, normalize_name

_FAKE_DIRECTORY = {
    "0": {"title": "Apple Inc.", "ticker": "AAPL", "cik_str": 320193},
    "1": {"title": "Microsoft Corporation", "ticker": "MSFT", "cik_str": 789019},
    "2": {"title": "Apple Hospitality REIT, Inc.", "ticker": "APLE", "cik_str": 1418121},
}


def _patch_directory(monkeypatch):
    monkeypatch.setattr(company_lookup, "load_company_tickers", lambda: _FAKE_DIRECTORY)


def test_normalize_name_collapses_whitespace_and_case():
    assert normalize_name("  Apple   INC  ") == "apple inc"


def test_ticker_match_wins(monkeypatch):
    _patch_directory(monkeypatch)
    match = find_company_match("anything", ticker="msft")
    assert match["cik"] == "0000789019"
    assert match["ticker"] == "MSFT"


def test_exact_name_match_zero_pads_cik(monkeypatch):
    _patch_directory(monkeypatch)
    match = find_company_match("Apple Inc.")
    assert match["cik"] == "0000320193"  # zero-padded to 10 digits
    assert match["company_name"] == "Apple Inc."


def test_partial_name_match(monkeypatch):
    _patch_directory(monkeypatch)
    match = find_company_match("Microsoft")
    assert match["cik"] == "0000789019"


def test_no_match_returns_none(monkeypatch):
    _patch_directory(monkeypatch)
    assert find_company_match("Nonexistent Company XYZ") is None


def test_ticker_match_prefers_name_overlap(monkeypatch):
    # Two filers, but only the ticker narrows it; name overlap is a tie-breaker.
    monkeypatch.setattr(
        company_lookup,
        "load_company_tickers",
        lambda: {
            "0": {"title": "Apple Inc.", "ticker": "AAPL", "cik_str": 320193},
            "1": {"title": "Apple Hospitality REIT, Inc.", "ticker": "AAPL", "cik_str": 1418121},
        },
    )
    match = find_company_match("Apple Hospitality", ticker="AAPL")
    assert match["cik"] == "0001418121"  # the name-overlapping one wins

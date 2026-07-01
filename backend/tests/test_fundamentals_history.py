"""Tests for the annual-fundamentals extractor.

The tricky, must-not-regress behavior: annual snapshots are keyed by the fact's
`end_date`, never its (unreliable) `fy` field, and the latest-filed value wins per
period so restatements supersede originals. These tests seed an isolated in-memory
DB and assert exactly that, plus that interim (10-Q) facts are excluded.
"""

from backend.app.fundamentals_history import annual_fact_series, annual_fundamentals
from backend.app.models import CompanyFact


def make_fact(cik, tag, value, end_date, filed, **overrides):
    defaults = dict(
        taxonomy="us-gaap",
        unit="USD",
        fiscal_year=2024,
        fiscal_period="FY",
        form="10-K",
    )
    defaults.update(overrides)
    return CompanyFact(cik=cik, tag=tag, value=value, end_date=end_date, filed=filed, **defaults)


def seed(session_factory, facts):
    with session_factory() as session:
        session.add_all(facts)
        session.commit()


def test_snapshots_sorted_by_period_end_newest_first(patch_fundamentals_history_db):
    cik = "0000000001"
    seed(
        patch_fundamentals_history_db,
        [
            make_fact(cik, "Assets", 100, end_date="2022-12-31", filed="2023-02-01"),
            make_fact(cik, "Assets", 200, end_date="2024-12-31", filed="2025-02-01"),
            make_fact(cik, "Assets", 150, end_date="2023-12-31", filed="2024-02-01"),
        ],
    )
    hist = annual_fundamentals(cik)
    assert [h["period_end"] for h in hist] == ["2024-12-31", "2023-12-31", "2022-12-31"]
    assert hist[0]["assets"] == 200  # newest period is [0] (the "current" year)
    assert hist[1]["assets"] == 150  # prior year is [1]


def test_latest_filed_wins_per_period_restatement_aware(patch_fundamentals_history_db):
    """Two filings report the same period end; the later filing's value must win."""
    cik = "0000000002"
    seed(
        patch_fundamentals_history_db,
        [
            make_fact(cik, "StockholdersEquity", 500, end_date="2023-12-31", filed="2024-02-01"),
            # A later 10-K re-presents 2023 equity as 480 (a restatement).
            make_fact(cik, "StockholdersEquity", 480, end_date="2023-12-31", filed="2025-02-01"),
        ],
    )
    hist = annual_fundamentals(cik)
    assert len(hist) == 1
    assert hist[0]["equity"] == 480  # restated (latest-filed) value


def test_fy_field_is_ignored_period_end_is_authoritative(patch_fundamentals_history_db):
    """A comparative tagged with a *filing* fy must land in its real (end_date) year."""
    cik = "0000000003"
    seed(
        patch_fundamentals_history_db,
        [
            # Both rows carry fiscal_year=2025 (the filing's fy) but cover different periods.
            make_fact(cik, "Assets", 900, end_date="2024-12-31", filed="2025-02-01", fiscal_year=2025),
            make_fact(cik, "Assets", 800, end_date="2023-12-31", filed="2025-02-01", fiscal_year=2025),
        ],
    )
    hist = annual_fundamentals(cik)
    # Correctly split into two periods by end_date, not collapsed under fy=2025.
    assert {h["period_end"]: h["assets"] for h in hist} == {
        "2024-12-31": 900,
        "2023-12-31": 800,
    }


def test_interim_forms_are_excluded(patch_fundamentals_history_db):
    cik = "0000000004"
    seed(
        patch_fundamentals_history_db,
        [
            make_fact(cik, "Revenues", 1000, end_date="2024-12-31", filed="2025-02-01", form="10-K"),
            make_fact(cik, "Revenues", 250, end_date="2024-03-31", filed="2024-04-15", form="10-Q"),
        ],
    )
    hist = annual_fundamentals(cik)
    assert len(hist) == 1  # only the annual 10-K period survives
    assert hist[0]["period_end"] == "2024-12-31"


def test_share_units_are_selected_for_share_field(patch_fundamentals_history_db):
    cik = "0000000005"
    seed(
        patch_fundamentals_history_db,
        [
            make_fact(
                cik,
                "WeightedAverageNumberOfDilutedSharesOutstanding",
                16_000_000,
                end_date="2024-12-31",
                filed="2025-02-01",
                unit="shares",
            ),
        ],
    )
    with patch_fundamentals_history_db() as session:
        series = annual_fact_series(
            session,
            cik,
            ["WeightedAverageNumberOfDilutedSharesOutstanding"],
            shares=True,
        )
    assert series == {"2024-12-31": 16_000_000}


def test_empty_db_returns_empty_history(patch_fundamentals_history_db):
    assert annual_fundamentals("9999999999") == []

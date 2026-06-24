"""Tests for metrics: display formatting + the derived-ratio math.

The ratio math lives in `compute_basic_snapshot`, which reads XBRL facts out of
the DB, so these tests seed an isolated in-memory DB (see `patch_metrics_db`)
rather than mocking the math out — that exercises the real fact-selection path
*and* the ratio formulas together.
"""

import pytest

from backend.app.metrics import (
    compute_basic_snapshot,
    format_large_number,
    format_snapshot,
)
from backend.app.models import CompanyFact


def make_fact(cik, tag, value, **overrides):
    defaults = dict(
        taxonomy="us-gaap",
        unit="USD",
        fiscal_year=2023,
        fiscal_period="FY",
        form="10-K",
        filed="2024-01-01",
        end_date="2023-12-31",
    )
    defaults.update(overrides)
    return CompanyFact(cik=cik, tag=tag, value=value, **defaults)


def seed(session_factory, facts):
    with session_factory() as session:
        session.add_all(facts)
        session.commit()


# --- format_large_number ---------------------------------------------------

@pytest.mark.parametrize(
    "value, expected",
    [
        (1_500_000_000, "1.50B"),
        (2_500_000, "2.50M"),
        (999, "999.00"),
        (0, "0.00"),
        (-1_500_000_000, "-1.50B"),  # sign preserved; abs() only picks the scale
        (None, None),
    ],
)
def test_format_large_number(value, expected):
    assert format_large_number(value) == expected


def test_format_snapshot_ratios_as_percent_money_as_scaled():
    snapshot = {
        "revenue": 1_000_000_000,
        "operating_margin": 0.25,
        "roe_proxy": 0.1,
        "net_income": None,
    }
    formatted = format_snapshot(snapshot)
    assert formatted["revenue"] == "1.00B"
    assert formatted["operating_margin"] == "25.00%"
    assert formatted["roe_proxy"] == "10.00%"
    assert formatted["net_income"] is None


# --- compute_basic_snapshot ratios ----------------------------------------

def test_compute_basic_snapshot_full_ratios(patch_metrics_db):
    cik = "0000000001"
    seed(
        patch_metrics_db,
        [
            make_fact(cik, "Revenues", 1000),
            make_fact(cik, "OperatingIncomeLoss", 250),
            make_fact(cik, "NetIncomeLoss", 200),
            make_fact(cik, "StockholdersEquity", 800),
            make_fact(cik, "Assets", 2000),
            make_fact(cik, "Liabilities", 1200),
            make_fact(cik, "NetCashProvidedByUsedInOperatingActivities", 300),
            make_fact(cik, "PaymentsToAcquirePropertyPlantAndEquipment", 50),
        ],
    )

    snap = compute_basic_snapshot(cik)

    assert snap["revenue"] == 1000
    assert snap["operating_margin"] == pytest.approx(0.25)       # 250 / 1000
    assert snap["roe_proxy"] == pytest.approx(0.25)              # 200 / 800
    assert snap["free_cash_flow_proxy"] == pytest.approx(250)    # 300 - |50|
    assert snap["net_assets"] == pytest.approx(800)             # 2000 - 1200


def test_compute_basic_snapshot_capex_sign_uses_abs(patch_metrics_db):
    """Filers report capex with inconsistent sign; FCF must use its magnitude."""
    cik = "0000000009"
    seed(
        patch_metrics_db,
        [
            make_fact(cik, "NetCashProvidedByUsedInOperatingActivities", 300),
            make_fact(cik, "PaymentsToAcquirePropertyPlantAndEquipment", -50),
        ],
    )
    snap = compute_basic_snapshot(cik)
    assert snap["free_cash_flow_proxy"] == pytest.approx(250)


def test_compute_basic_snapshot_guards_missing_and_zero(patch_metrics_db):
    """Missing inputs / divide-by-zero must yield None, never raise."""
    cik = "0000000002"
    seed(
        patch_metrics_db,
        [
            make_fact(cik, "Revenues", 0),               # zero revenue
            make_fact(cik, "OperatingIncomeLoss", 100),
            make_fact(cik, "NetIncomeLoss", 50),         # but no equity seeded
            make_fact(cik, "Assets", 500),               # but no liabilities seeded
        ],
    )
    snap = compute_basic_snapshot(cik)

    assert snap["operating_margin"] is None        # revenue == 0 guard
    assert snap["roe_proxy"] is None               # equity missing
    assert snap["free_cash_flow_proxy"] is None    # ocf/capex missing
    assert snap["net_assets"] is None              # liabilities missing


def test_compute_basic_snapshot_picks_latest_filed(patch_metrics_db):
    """latest_fact must select the most recently *filed* value."""
    cik = "0000000003"
    seed(
        patch_metrics_db,
        [
            make_fact(cik, "Revenues", 500, filed="2022-01-01", fiscal_year=2021),
            make_fact(cik, "Revenues", 1000, filed="2024-01-01", fiscal_year=2023),
        ],
    )
    snap = compute_basic_snapshot(cik)
    assert snap["revenue"] == 1000


def test_compute_basic_snapshot_empty_db_is_all_none(patch_metrics_db):
    snap = compute_basic_snapshot("9999999999")
    assert snap["revenue"] is None
    assert snap["operating_margin"] is None
    assert snap["net_assets"] is None

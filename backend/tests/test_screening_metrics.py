"""Tests for the pure screening metrics (no DB): Piotroski / Altman / accruals /
ROIC / FCF yield. Values are checked against hand computations, with explicit
coverage of the missing-data and divide-by-zero guards."""

import pytest

from backend.app.screening.metrics import (
    compute_accruals,
    compute_altman,
    compute_fcf_yield,
    compute_piotroski,
    compute_roic,
    effective_tax_rate,
    free_cash_flow,
    gross_profit_value,
    total_liabilities,
)


# --- helpers ---------------------------------------------------------------

def strong_pair():
    """A current/prior pair engineered so all 9 Piotroski tests pass."""
    current = dict(
        revenue=1000, net_income=150, assets=2000, current_assets=800,
        current_liabilities=400, liabilities=900, equity=1100, retained_earnings=700,
        operating_cash_flow=200, capex=40, operating_income=220, gross_profit=450,
        long_term_debt=300, diluted_shares=100, income_tax=42, pretax_income=200,
    )
    prior = dict(
        revenue=900, net_income=110, assets=1900, current_assets=700,
        current_liabilities=420, liabilities=950, equity=950, retained_earnings=560,
        operating_cash_flow=160, capex=45, operating_income=180, gross_profit=380,
        long_term_debt=340, diluted_shares=102, income_tax=35, pretax_income=170,
    )
    return current, prior


# --- Piotroski -------------------------------------------------------------

def test_piotroski_all_nine_pass():
    current, prior = strong_pair()
    result = compute_piotroski(current, prior)
    assert result["f_score"] == 9
    assert result["tests_available"] == 9
    assert result["complete"] is True
    assert all(result["tests"].values())


def test_piotroski_accrual_quality_flag_when_cash_below_earnings():
    current, prior = strong_pair()
    current["operating_cash_flow"] = 100  # now CFO (100) < NI (150) -> fails test 4
    result = compute_piotroski(current, prior)
    assert result["tests"]["accrual_quality"] is False
    assert result["f_score"] == 8


def test_piotroski_missing_year_over_year_marks_tests_unavailable():
    current, _ = strong_pair()
    result = compute_piotroski(current, {})  # no prior -> YoY tests can't compute
    # The 3 point-in-time tests still evaluate; the 6 YoY tests are None.
    assert result["tests"]["roa_positive"] is True
    assert result["tests"]["cfo_positive"] is True
    assert result["tests"]["roa_improving"] is None
    assert result["tests_available"] == 3
    assert result["complete"] is False


def test_piotroski_zero_denominators_do_not_raise():
    current = dict(revenue=0, net_income=10, assets=0, current_liabilities=0)
    result = compute_piotroski(current, {})
    assert result["tests"]["roa_positive"] is None  # assets == 0 guard
    assert isinstance(result["f_score"], int)


# --- Altman ----------------------------------------------------------------

def test_altman_book_model_without_market_cap():
    current, _ = strong_pair()
    result = compute_altman(current)
    assert result["model"] == "z_double_prime"
    # 6.56*.2 + 3.26*.35 + 6.72*.11 + 1.05*(1100/900) = 4.476
    assert result["z_score"] == pytest.approx(4.476, abs=0.01)
    assert result["zone"] == "safe"


def test_altman_classic_model_with_market_cap():
    current, _ = strong_pair()
    result = compute_altman(current, market_cap=5000)
    assert result["model"] == "classic"
    assert set(result["components"]) == {"x1", "x2", "x3", "x4", "x5"}
    assert result["zone"] == "safe"


def test_altman_distress_zone_on_weak_balance_sheet():
    current = dict(
        assets=2000, liabilities=1950, current_assets=800, current_liabilities=400,
        retained_earnings=-500, operating_income=-30, revenue=1000, equity=50,
    )
    result = compute_altman(current, market_cap=200)  # classic model
    assert result["zone"] == "distress"
    assert result["z_score"] < 1.81


def test_altman_none_when_core_inputs_missing():
    assert compute_altman({"assets": 0, "liabilities": 100})["z_score"] is None
    # Missing working-capital inputs leave a component None -> unscorable.
    result = compute_altman({"assets": 1000, "liabilities": 500, "retained_earnings": 100,
                             "operating_income": 50, "revenue": 800})
    assert result["z_score"] is None


def test_total_liabilities_derived_from_identity_when_untagged():
    assert total_liabilities({"liabilities": 900}) == 900              # reported wins
    assert total_liabilities({"assets": 1000, "equity": 300}) == 700   # assets - equity
    assert total_liabilities({"assets": 1000}) is None                 # can't derive


def test_altman_uses_derived_liabilities_when_total_untagged():
    # No `liabilities` tag (Coca-Cola pattern) but assets + equity present -> scorable.
    current = dict(
        assets=2000, equity=1100, current_assets=800, current_liabilities=400,
        retained_earnings=700, operating_income=220, revenue=1000,
    )
    result = compute_altman(current)  # book Z''; x4 uses derived liabilities 900
    assert result["z_score"] is not None
    assert result["components"]["x4"] == pytest.approx(1100 / (2000 - 1100))


# --- accruals --------------------------------------------------------------

def test_accruals_negative_when_cash_exceeds_earnings():
    current, prior = strong_pair()  # NI 150, CFO 200, avg assets (2000+1900)/2 = 1950
    assert compute_accruals(current, prior) == pytest.approx((150 - 200) / 1950)


def test_accruals_uses_current_assets_when_no_prior():
    current = dict(net_income=100, operating_cash_flow=40, assets=1000)
    assert compute_accruals(current, {}) == pytest.approx((100 - 40) / 1000)


def test_accruals_none_when_inputs_missing():
    assert compute_accruals({"net_income": 100}, {}) is None
    assert compute_accruals({"net_income": 100, "operating_cash_flow": 50, "assets": 0}, {}) is None


# --- ROIC ------------------------------------------------------------------

def test_roic_uses_effective_tax_rate():
    current, _ = strong_pair()  # EBIT 220, tax 42/200=.21, IC 1100+300=1400
    result = compute_roic(current)
    assert result["tax_rate"] == pytest.approx(0.21)
    assert result["roic"] == pytest.approx(220 * 0.79 / 1400)


def test_effective_tax_rate_defaults_and_clamps():
    assert effective_tax_rate({}) == 0.21                                   # missing -> default
    assert effective_tax_rate({"income_tax": -5, "pretax_income": 100}) == 0.21  # benefit -> default
    assert effective_tax_rate({"income_tax": 90, "pretax_income": 100}) == 0.35  # clamped high
    assert effective_tax_rate({"income_tax": 10, "pretax_income": -50}) == 0.21  # loss -> default


def test_roic_none_on_nonpositive_invested_capital():
    current = dict(operating_income=100, equity=-200, long_term_debt=50)
    assert compute_roic(current)["roic"] is None


# --- FCF yield -------------------------------------------------------------

def test_free_cash_flow_uses_capex_magnitude():
    assert free_cash_flow({"operating_cash_flow": 300, "capex": -50}) == 250
    assert free_cash_flow({"operating_cash_flow": 300, "capex": 50}) == 250
    assert free_cash_flow({"operating_cash_flow": 300}) is None


def test_fcf_yield_requires_market_cap():
    current = dict(operating_cash_flow=200, capex=40, net_income=150)
    assert compute_fcf_yield(current)["fcf_yield"] is None
    result = compute_fcf_yield(current, market_cap=5000)
    assert result["fcf_yield"] == pytest.approx(160 / 5000)
    assert result["earnings_yield"] == pytest.approx(150 / 5000)


def test_gross_profit_falls_back_to_revenue_minus_cost():
    assert gross_profit_value({"gross_profit": 450}) == 450
    assert gross_profit_value({"revenue": 1000, "cost_of_revenue": 600}) == 400
    assert gross_profit_value({"revenue": 1000}) is None

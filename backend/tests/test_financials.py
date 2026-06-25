"""Tests for the pure per-category financial scorers (financials.py).

These grade an XBRL-derived snapshot dict; score_financial_quality (the DB-backed
orchestrator that builds the snapshot) is exercised indirectly via test_opinion.
"""

from backend.app.scoring.financials import (
    clamp_score,
    score_balance_sheet_strength,
    score_capital_efficiency,
    score_cash_generation,
    score_leverage,
    score_profitability,
)


def test_clamp_score_rounds_and_bounds():
    assert clamp_score(25) == 20       # capped at the category high
    assert clamp_score(-5) == 0        # floored at 0
    assert clamp_score(15.5) == 15.5   # in-bounds value passes through


def test_profitability_margin_bands():
    assert score_profitability({"operating_margin": 0.35})[0] == 20
    assert score_profitability({"operating_margin": 0.22})[0] == 16
    assert score_profitability({"operating_margin": 0.12})[0] == 10
    assert score_profitability({"operating_margin": 0.02})[0] == 5
    assert score_profitability({"operating_margin": -0.1})[0] == 0


def test_profitability_missing_data_is_zero_with_note():
    score, notes = score_profitability({})
    assert score == 0
    assert any("unavailable" in n.lower() for n in notes)


def test_cash_generation_full_marks_and_no_data():
    full = score_cash_generation(
        {"operating_cash_flow": 100, "free_cash_flow_proxy": 50, "revenue": 200}
    )
    assert full[0] == 20  # 8 (OCF) + 8 (FCF) + 4 (FCF margin 0.25 >= 0.20)
    assert score_cash_generation({})[0] == 0


def test_leverage_debt_to_equity_and_fallback():
    assert score_leverage({"long_term_debt": 100, "equity": 1000})[0] == 20   # d/e 0.1
    assert score_leverage({"long_term_debt": 1500, "equity": 1000})[0] == 10  # d/e 1.5
    assert score_leverage({"long_term_debt": 100, "assets": 1000})[0] == 16   # d/a fallback 0.1
    assert score_leverage({})[0] == 0  # no debt data -> conservative 0


def test_balance_sheet_strength_bands():
    assert score_balance_sheet_strength({"assets": 1000, "liabilities": 400})[0] == 20
    assert score_balance_sheet_strength({"assets": 1000, "liabilities": 900})[0] == 4
    assert score_balance_sheet_strength({})[0] == 0


def test_capital_efficiency_roe_bands():
    assert score_capital_efficiency({"roe_proxy": 0.30})[0] == 20
    assert score_capital_efficiency({"roe_proxy": 0.10})[0] == 10
    assert score_capital_efficiency({"roe_proxy": -0.05})[0] == 0
    assert score_capital_efficiency({})[0] == 0

"""Tests for the price -> return -> portfolio math (offline; no yfinance)."""

import numpy as np
import pandas as pd
import pytest

from backend.app.factors import prices as prices_mod


def _price_frame():
    dates = pd.bdate_range("2024-01-01", periods=3)
    return pd.DataFrame({"AAPL": [100.0, 110.0, 121.0], "MSFT": [200.0, 200.0, 220.0]}, index=dates)


def test_prices_to_returns_basic_and_drops_leading_row():
    returns = prices_mod.prices_to_returns(_price_frame())
    assert len(returns) == 2  # leading all-NaN pct_change row dropped
    assert returns["AAPL"].tolist() == pytest.approx([0.10, 0.10])
    assert returns["MSFT"].tolist() == pytest.approx([0.00, 0.10])


def test_build_portfolio_equal_weight():
    returns = prices_mod.prices_to_returns(_price_frame())
    portfolio = prices_mod.build_portfolio_returns(returns, {"AAPL": 1.0, "MSFT": 1.0})
    # 0.5 * AAPL + 0.5 * MSFT
    assert portfolio.tolist() == pytest.approx([0.05, 0.10])
    assert portfolio.name == "portfolio"


def test_build_portfolio_renormalizes_over_present_tickers():
    returns = prices_mod.prices_to_returns(_price_frame())
    # GOOG has no column -> ignored; AAPL/MSFT renormalized to sum to 1.
    portfolio = prices_mod.build_portfolio_returns(
        returns, {"AAPL": 0.25, "MSFT": 0.25, "GOOG": 0.5}
    )
    assert portfolio.tolist() == pytest.approx([0.05, 0.10])


def test_build_portfolio_weighted():
    returns = prices_mod.prices_to_returns(_price_frame())
    portfolio = prices_mod.build_portfolio_returns(returns, {"AAPL": 0.8, "MSFT": 0.2})
    assert portfolio.tolist() == pytest.approx([0.8 * 0.10 + 0.2 * 0.0, 0.10])


def test_build_portfolio_raises_when_no_ticker_present():
    returns = prices_mod.prices_to_returns(_price_frame())
    with pytest.raises(ValueError, match="None of the requested tickers"):
        prices_mod.build_portfolio_returns(returns, {"TSLA": 1.0})


def test_build_portfolio_drops_days_with_a_missing_holding():
    dates = pd.bdate_range("2024-01-01", periods=3)
    returns = pd.DataFrame(
        {"AAPL": [0.01, 0.02, 0.03], "MSFT": [0.01, np.nan, 0.02]}, index=dates
    )
    portfolio = prices_mod.build_portfolio_returns(returns, {"AAPL": 0.5, "MSFT": 0.5})
    assert len(portfolio) == 2  # the day MSFT is NaN is dropped from the basket

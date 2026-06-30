"""Tests for the factor-attribution orchestrator (offline, injected loaders).

The price and factor loaders are passed in directly, so the whole pipeline runs
end-to-end on synthetic data with no network and no monkeypatching of internals.
"""

import json

import numpy as np
import pandas as pd
import pytest

from backend.app.factors import service
from backend.app.factors.regression import FACTOR_COLUMNS


def _synthetic_market(n=260, seed=3):
    """Return (prices_df, factors_df) sharing a date index, with realistic shapes."""
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2022-01-03", periods=n)
    factors = pd.DataFrame(
        {col: rng.normal(0.0003, 0.01, n) for col in FACTOR_COLUMNS}, index=dates
    )
    factors["RF"] = 0.00008

    def make_prices(betas, alpha):
        excess = alpha + factors[FACTOR_COLUMNS].values @ np.array(betas) + rng.normal(0, 0.003, n)
        total = excess + factors["RF"].values
        return 100 * np.cumprod(1 + total)

    prices = pd.DataFrame(
        {
            "AAPL": make_prices([1.2, -0.2, -0.3, 0.1, -0.05, 0.2], 0.0003),
            "MSFT": make_prices([1.0, -0.1, 0.1, 0.3, 0.0, 0.1], 0.0001),
        },
        index=dates,
    )
    return prices, factors


def _loaders(prices, factors):
    def price_loader(tickers, start, end):
        return prices[[t for t in tickers if t in prices.columns]]

    def factor_loader(start, end):
        return factors

    return price_loader, factor_loader


def test_happy_path_returns_full_contract():
    prices, factors = _synthetic_market()
    price_loader, factor_loader = _loaders(prices, factors)
    result = service.analyze_factor_exposure(
        [{"ticker": "AAPL", "weight": 0.6}, {"ticker": "MSFT", "weight": 0.4}],
        price_loader=price_loader,
        factor_loader=factor_loader,
    )

    assert "error" not in result
    json.dumps(result)  # JSON-serializable end to end
    assert set(result) >= {"portfolio", "factor_model", "factors", "full_sample", "rolling", "attribution"}
    assert result["portfolio"]["observations"] > 0
    assert result["factors"] == FACTOR_COLUMNS

    # Portfolio market beta ~ weighted average of the two stocks' market betas.
    expected_mkt = 0.6 * 1.2 + 0.4 * 1.0
    assert result["full_sample"]["betas"]["Mkt-RF"]["beta"] == pytest.approx(expected_mkt, abs=0.05)
    # Waterfall reconciles.
    attribution = result["attribution"]
    assert attribution["residual_annualized"] == pytest.approx(0.0, abs=1e-6)


def test_unknown_ticker_is_dropped_and_weights_renormalized():
    prices, factors = _synthetic_market()
    price_loader, factor_loader = _loaders(prices, factors)
    result = service.analyze_factor_exposure(
        [
            {"ticker": "AAPL", "weight": 0.5},
            {"ticker": "MSFT", "weight": 0.3},
            {"ticker": "NOPE", "weight": 0.2},
        ],
        price_loader=price_loader,
        factor_loader=factor_loader,
    )
    assert "NOPE" in result["portfolio"]["dropped_tickers"]
    weights = {h["ticker"]: h["weight"] for h in result["portfolio"]["holdings"]}
    assert "NOPE" not in weights
    assert sum(weights.values()) == pytest.approx(1.0)


def test_all_unknown_tickers_returns_error():
    prices, factors = _synthetic_market()
    price_loader, factor_loader = _loaders(prices, factors)
    result = service.analyze_factor_exposure(
        [{"ticker": "NOPE", "weight": 1.0}],
        price_loader=price_loader,
        factor_loader=factor_loader,
    )
    assert "error" in result


def test_insufficient_overlap_returns_error():
    prices, factors = _synthetic_market(n=30)  # < MIN_OBSERVATIONS
    price_loader, factor_loader = _loaders(prices, factors)
    result = service.analyze_factor_exposure(
        [{"ticker": "AAPL", "weight": 1.0}],
        price_loader=price_loader,
        factor_loader=factor_loader,
    )
    assert "error" in result
    assert "overlapping history" in result["error"]


def test_single_ticker_full_weight():
    prices, factors = _synthetic_market()
    price_loader, factor_loader = _loaders(prices, factors)
    result = service.analyze_factor_exposure(
        [{"ticker": "AAPL"}],  # weight defaults inside normalize_holdings
        price_loader=price_loader,
        factor_loader=factor_loader,
    )
    assert result["portfolio"]["holdings"] == [{"ticker": "AAPL", "weight": 1.0}]


def test_empty_holdings_returns_error():
    result = service.analyze_factor_exposure([])
    assert result == {"error": "No holdings provided."}


def test_negative_weight_returns_error():
    result = service.analyze_factor_exposure([{"ticker": "AAPL", "weight": -1.0}])
    assert "error" in result and "non-negative" in result["error"]


def test_normalize_holdings_dedupes_uppercases_and_renormalizes():
    weights = service.normalize_holdings(
        [{"ticker": "aapl", "weight": 1.0}, {"ticker": "AAPL", "weight": 1.0}, "msft"]
    )
    assert set(weights) == {"AAPL", "MSFT"}
    assert weights["AAPL"] == pytest.approx(2 / 3)
    assert weights["MSFT"] == pytest.approx(1 / 3)
    assert sum(weights.values()) == pytest.approx(1.0)

"""Factor-attribution orchestrator — portfolio in, full analysis out.

`analyze_factor_exposure` is the single entry point the `/factor-attribution`
endpoint calls. It:

  1. normalizes the holdings (tickers + weights, deduped and renormalized),
  2. builds the portfolio's daily return series from market prices,
  3. loads the Fama-French 5 + Momentum factors and the risk-free rate,
  4. aligns them and forms excess returns (r_p − r_f),
  5. runs the full-sample and rolling factor regressions,
  6. builds the return-attribution waterfall,

and returns one JSON-serializable dict — the contract the frontend dashboard
renders. The price and factor loaders are injectable so the whole pipeline is
exercised offline with synthetic data (no network). On any data problem (unknown
tickers, too little overlapping history) it returns a dict with an `error` key
instead of raising, mirroring the `/analyze` endpoint's style.
"""

import logging
from datetime import date, timedelta
from typing import Callable

import pandas as pd

from .attribution import build_attribution
from .factor_data import load_factor_returns
from .prices import build_portfolio_returns, download_adjusted_prices, prices_to_returns
from .regression import (
    DEFAULT_ROLLING_WINDOW,
    FACTOR_COLUMNS,
    fit_factor_model,
    run_rolling_regression,
    summarize_regression,
)

logger = logging.getLogger(__name__)

# A factor regression needs comfortably more rows than its 7 parameters; below
# this many overlapping days the estimates aren't worth reporting.
MIN_OBSERVATIONS = 60
# Default history pulled when the caller doesn't specify a start date.
DEFAULT_LOOKBACK_YEARS = 5

PriceLoader = Callable[[list[str], str | None, str | None], pd.DataFrame]
FactorLoader = Callable[[str | None, str | None], pd.DataFrame]


def normalize_holdings(holdings: list) -> dict[str, float]:
    """Turn raw holdings into a {TICKER: weight} dict summing to 1.

    Accepts entries shaped like {"ticker": "AAPL", "weight": 0.5} or bare ticker
    strings (weight defaults to 1.0). Tickers are upper-cased and de-duplicated
    (weights summed); the result is renormalized to sum to 1. Raises ValueError
    on empty/invalid input.
    """
    if not holdings:
        raise ValueError("No holdings provided.")

    weights: dict[str, float] = {}
    for item in holdings:
        if isinstance(item, str):
            ticker, raw_weight = item, 1.0
        elif isinstance(item, dict):
            ticker = item.get("ticker", "")
            raw_weight = item.get("weight", 1.0)
        else:
            raise ValueError(f"Invalid holding entry: {item!r}")

        if not ticker or not str(ticker).strip():
            raise ValueError("A holding is missing its ticker symbol.")
        ticker = str(ticker).strip().upper()

        try:
            weight = float(raw_weight)
        except (TypeError, ValueError):
            raise ValueError(f"Invalid weight for {ticker}: {raw_weight!r}")
        if weight < 0:
            raise ValueError(f"Weight for {ticker} must be non-negative.")

        weights[ticker] = weights.get(ticker, 0.0) + weight

    total = sum(weights.values())
    if total <= 0:
        raise ValueError("Portfolio weights must sum to a positive number.")
    return {ticker: weight / total for ticker, weight in weights.items()}


def _resolve_date_range(start_date: str | None, end_date: str | None) -> tuple[str, str]:
    """Fill in a default [start, end] window (last DEFAULT_LOOKBACK_YEARS years)."""
    end = end_date or date.today().isoformat()
    if start_date:
        return start_date, end
    end_dt = date.fromisoformat(end)
    start_dt = end_dt - timedelta(days=365 * DEFAULT_LOOKBACK_YEARS + 5)
    return start_dt.isoformat(), end


def analyze_factor_exposure(
    holdings: list,
    start_date: str | None = None,
    end_date: str | None = None,
    rolling_window: int = DEFAULT_ROLLING_WINDOW,
    price_loader: PriceLoader | None = None,
    factor_loader: FactorLoader | None = None,
) -> dict:
    """Run the full factor-attribution pipeline; return the dashboard dict.

    `price_loader` / `factor_loader` default to the live yfinance / Ken French
    loaders but can be injected (tests pass synthetic data). Returns `{"error": …}`
    on any recoverable data problem rather than raising.
    """
    price_loader = price_loader or download_adjusted_prices
    factor_loader = factor_loader or load_factor_returns

    try:
        weights = normalize_holdings(holdings)
    except ValueError as exc:
        return {"error": str(exc)}

    start, end = _resolve_date_range(start_date, end_date)

    # --- Left-hand side: build the portfolio return series from prices ---
    try:
        prices = price_loader(list(weights), start, end)
    except Exception as exc:  # network / provider failure
        logger.exception("Factor attribution: price download failed")
        return {"error": f"Could not download price data: {exc}"}

    if prices is None or prices.empty:
        return {"error": "No price data returned for the requested tickers."}

    returns = prices_to_returns(prices)
    present = [ticker for ticker in weights if ticker in returns.columns]
    dropped = [ticker for ticker in weights if ticker not in present]
    if not present:
        return {"error": "None of the requested tickers returned usable price history."}

    present_total = sum(weights[ticker] for ticker in present)
    normalized_weights = {ticker: weights[ticker] / present_total for ticker in present}

    try:
        portfolio = build_portfolio_returns(returns, normalized_weights)
    except ValueError as exc:
        return {"error": str(exc)}

    # --- Right-hand side: load the Fama-French factors + risk-free rate ---
    try:
        factors = factor_loader(start, end)
    except Exception as exc:
        logger.exception("Factor attribution: factor download failed")
        return {"error": f"Could not load Fama-French factor data: {exc}"}

    common = portfolio.index.intersection(factors.index)
    if len(common) == 0:
        return {"error": "No overlapping dates between price history and factor data."}

    portfolio = portfolio.loc[common]
    factors_common = factors.loc[common]
    risk_free = factors_common["RF"] if "RF" in factors_common.columns else 0.0
    excess = (portfolio - risk_free).rename("excess")

    usable = pd.concat([excess, factors_common[FACTOR_COLUMNS]], axis=1).dropna()
    if len(usable) < MIN_OBSERVATIONS:
        return {
            "error": (
                f"Not enough overlapping history to estimate factor exposures "
                f"(need >= {MIN_OBSERVATIONS} trading days, have {len(usable)})."
            )
        }

    # --- Estimate + attribute (one fit shared by the summary and the waterfall) ---
    fit = fit_factor_model(excess, factors_common)
    regression = summarize_regression(fit)
    rolling = run_rolling_regression(excess, factors_common, window=rolling_window)
    attribution = build_attribution(fit)

    index = usable.index
    return {
        "portfolio": {
            "holdings": [
                {"ticker": ticker, "weight": round(weight, 6)}
                for ticker, weight in normalized_weights.items()
            ],
            "dropped_tickers": dropped,
            "start_date": start,
            "end_date": end,
            "observations": int(len(usable)),
            "first_date": index.min().strftime("%Y-%m-%d"),
            "last_date": index.max().strftime("%Y-%m-%d"),
        },
        "factor_model": "Fama-French 5 Factor + Momentum",
        "factors": FACTOR_COLUMNS,
        "full_sample": regression,
        "rolling": rolling,
        "attribution": attribution,
    }

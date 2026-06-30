"""OLS factor regressions — static (full-sample) and rolling.

Regresses portfolio *excess* returns on the Fama-French 5 + Momentum factors:

    r_p - r_f = alpha + b_mkt·(Mkt-RF) + b_smb·SMB + b_hml·HML
                      + b_rmw·RMW + b_cma·CMA + b_mom·Mom + e

The intercept is **alpha** — the average return left unexplained by factor
exposure (the portfolio's idiosyncratic "edge" or skill). The slopes are the
**betas** — how strongly the portfolio is tilted toward each factor. The
full-sample fit also reports standard errors / t-stats / p-values / a 95%
confidence interval for every coefficient, plus R². The rolling fit
(statsmodels `RollingOLS`, default 126-trading-day ≈ 6-month window) shows how
those exposures drift through time.

Everything returned is plain Python floats / strings (no numpy or pandas
scalars) so the result is directly JSON-serializable by the API layer.
"""

from typing import NamedTuple

import numpy as np
import pandas as pd
import statsmodels.api as sm
from statsmodels.regression.rolling import RollingOLS

# The six regression factors (RF is excluded — it defines *excess* returns, it is
# not a right-hand-side factor). Order is the conventional FF5 + Momentum order.
FACTOR_COLUMNS = ["Mkt-RF", "SMB", "HML", "RMW", "CMA", "Mom"]

# Human-readable labels for the dashboard / attribution waterfall.
FACTOR_LABELS = {
    "Mkt-RF": "Market",
    "SMB": "Size (SMB)",
    "HML": "Value (HML)",
    "RMW": "Profitability (RMW)",
    "CMA": "Investment (CMA)",
    "Mom": "Momentum",
}

TRADING_DAYS_PER_YEAR = 252
DEFAULT_ROLLING_WINDOW = 126
SIGNIFICANCE_LEVEL = 0.05


class FactorFit(NamedTuple):
    """One fitted OLS model plus the exact aligned data it was fit on.

    Sharing this across the summary and the attribution waterfall means both read
    the *same* full-precision coefficients and means — so the waterfall reconciles
    to the total instead of accumulating display-rounding error.
    """

    model: sm.regression.linear_model.RegressionResultsWrapper
    y: pd.Series
    x: pd.DataFrame


def _align(excess_returns: pd.Series, factors: pd.DataFrame, factor_columns: list[str]):
    """Inner-align the dependent series and factor columns, dropping any NaN rows."""
    data = pd.concat([excess_returns.rename("y"), factors[factor_columns]], axis=1)
    data = data.dropna()
    return data["y"], data[factor_columns]


def fit_factor_model(
    excess_returns: pd.Series,
    factors: pd.DataFrame,
    factor_columns: list[str] = FACTOR_COLUMNS,
) -> FactorFit:
    """Align the data and fit one full-sample OLS (with intercept = alpha)."""
    y, x = _align(excess_returns, factors, factor_columns)
    model = sm.OLS(y, sm.add_constant(x)).fit()
    return FactorFit(model=model, y=y, x=x)


def _coef_block(name: str, params, bse, tvalues, pvalues, conf_int) -> dict:
    """Build the per-coefficient stats dict (all native floats)."""
    low, high = conf_int.loc[name]
    return {
        "estimate": round(float(params[name]), 6),
        "std_err": round(float(bse[name]), 6),
        "t_stat": round(float(tvalues[name]), 4),
        "p_value": round(float(pvalues[name]), 4),
        "conf_int": [round(float(low), 6), round(float(high), 6)],
        "significant": bool(float(pvalues[name]) < SIGNIFICANCE_LEVEL),
    }


def summarize_regression(fit: FactorFit) -> dict:
    """Format a fitted model into the JSON `full_sample` block.

    Returns a dict with `alpha` (daily + annualized, with significance), per-factor
    `betas`, and `r_squared` / `adj_r_squared` / `n_obs`.
    """
    model = fit.model
    factor_columns = list(fit.x.columns)

    params, bse = model.params, model.bse
    tvalues, pvalues = model.tvalues, model.pvalues
    conf_int = model.conf_int()

    alpha_daily = float(params["const"])
    alpha_block = _coef_block("const", params, bse, tvalues, pvalues, conf_int)
    alpha = {
        "daily": round(alpha_daily, 6),
        "annualized": round(alpha_daily * TRADING_DAYS_PER_YEAR, 6),
        "std_err": alpha_block["std_err"],
        "t_stat": alpha_block["t_stat"],
        "p_value": alpha_block["p_value"],
        "conf_int_daily": alpha_block["conf_int"],
        "significant": alpha_block["significant"],
    }

    betas = {}
    for factor in factor_columns:
        block = _coef_block(factor, params, bse, tvalues, pvalues, conf_int)
        betas[factor] = {
            "label": FACTOR_LABELS.get(factor, factor),
            "beta": block["estimate"],
            "std_err": block["std_err"],
            "t_stat": block["t_stat"],
            "p_value": block["p_value"],
            "conf_int": block["conf_int"],
            "significant": block["significant"],
        }

    return {
        "alpha": alpha,
        "betas": betas,
        "r_squared": round(float(model.rsquared), 4),
        "adj_r_squared": round(float(model.rsquared_adj), 4),
        "n_obs": int(model.nobs),
    }


def run_factor_regression(
    excess_returns: pd.Series,
    factors: pd.DataFrame,
    factor_columns: list[str] = FACTOR_COLUMNS,
) -> dict:
    """Fit + summarize in one call (convenience for standalone use / tests)."""
    return summarize_regression(fit_factor_model(excess_returns, factors, factor_columns))


def run_rolling_regression(
    excess_returns: pd.Series,
    factors: pd.DataFrame,
    window: int = DEFAULT_ROLLING_WINDOW,
    factor_columns: list[str] = FACTOR_COLUMNS,
) -> dict:
    """Rolling-window OLS to chart how betas / alpha / R² drift over time.

    Uses statsmodels `RollingOLS` over a `window`-day window. Returns parallel
    arrays keyed by an ISO-date axis: one beta series per factor, the annualized
    alpha, and R². If there is less history than one full window, returns a
    structurally-identical-but-empty result with `available: False`.
    """
    y, x = _align(excess_returns, factors, factor_columns)

    if len(y) < window:
        return {
            "window": window,
            "available": False,
            "observations": 0,
            "dates": [],
            "betas": {factor: [] for factor in factor_columns},
            "alpha_annualized": [],
            "r_squared": [],
        }

    fit = RollingOLS(y, sm.add_constant(x), window=window).fit()
    params = fit.params.dropna()  # drop the leading rows before a full window
    r_squared = fit.rsquared.reindex(params.index)

    dates = [ts.strftime("%Y-%m-%d") for ts in params.index]
    betas = {
        factor: [round(float(value), 6) for value in params[factor]]
        for factor in factor_columns
    }
    alpha_annualized = [
        round(float(value) * TRADING_DAYS_PER_YEAR, 6) for value in params["const"]
    ]
    r_squared_values = [
        round(float(value), 4) if not np.isnan(value) else None for value in r_squared
    ]

    return {
        "window": window,
        "available": True,
        "observations": len(dates),
        "dates": dates,
        "betas": betas,
        "alpha_annualized": alpha_annualized,
        "r_squared": r_squared_values,
    }

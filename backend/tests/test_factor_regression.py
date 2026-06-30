"""Tests for the OLS factor regressions (offline, synthetic data).

The trick that makes these deterministic: *manufacture* the dependent series from
known alpha + betas (plus a little noise), then assert the regression recovers
them. With a clean factor model the estimates land right on the truth.
"""

import json

import numpy as np
import pandas as pd
import pytest

from backend.app.factors import regression as reg

TRUE_ALPHA = 0.0003
TRUE_BETAS = {"Mkt-RF": 1.10, "SMB": 0.40, "HML": -0.30, "RMW": 0.20, "CMA": -0.10, "Mom": 0.25}


def _synthetic(n=400, noise=1e-5, seed=7):
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2020-01-01", periods=n)
    factors = pd.DataFrame(
        {col: rng.normal(0.0003, 0.01, n) for col in reg.FACTOR_COLUMNS}, index=dates
    )
    factors["RF"] = 0.0001
    beta_vec = np.array([TRUE_BETAS[c] for c in reg.FACTOR_COLUMNS])
    excess = TRUE_ALPHA + factors[reg.FACTOR_COLUMNS].values @ beta_vec + rng.normal(0, noise, n)
    return pd.Series(excess, index=dates, name="excess"), factors


def test_full_sample_recovers_alpha_and_betas():
    excess, factors = _synthetic()
    result = reg.run_factor_regression(excess, factors)

    assert result["alpha"]["daily"] == pytest.approx(TRUE_ALPHA, abs=1e-4)
    for factor, true_beta in TRUE_BETAS.items():
        assert result["betas"][factor]["beta"] == pytest.approx(true_beta, abs=0.02)
    assert result["r_squared"] >= 0.99
    assert result["n_obs"] == 400


def test_full_sample_structure_is_json_native():
    excess, factors = _synthetic()
    result = reg.run_factor_regression(excess, factors)

    json.dumps(result)  # must serialize: no numpy/pandas scalars leak through
    alpha = result["alpha"]
    assert set(alpha) >= {"daily", "annualized", "t_stat", "p_value", "conf_int_daily", "significant"}
    # annualized is daily x 252 (computed from full precision, so allow the
    # tolerance the 6-dp display rounding of `daily` implies: ~252 * 5e-7).
    assert alpha["annualized"] == pytest.approx(alpha["daily"] * 252, abs=2e-4)
    assert isinstance(alpha["significant"], bool)

    block = result["betas"]["Mkt-RF"]
    assert set(block) >= {"label", "beta", "std_err", "t_stat", "p_value", "conf_int", "significant"}
    low, high = block["conf_int"]
    assert low <= block["beta"] <= high


def test_market_beta_is_strongly_significant():
    excess, factors = _synthetic()
    result = reg.run_factor_regression(excess, factors)
    assert result["betas"]["Mkt-RF"]["significant"] is True
    assert result["betas"]["Mkt-RF"]["p_value"] < 0.01


def test_fit_drops_nan_rows():
    excess, factors = _synthetic(n=120)
    excess.iloc[5] = np.nan  # one missing observation
    fit = reg.fit_factor_model(excess, factors)
    assert int(fit.model.nobs) == 119


def test_rolling_shapes_align():
    excess, factors = _synthetic(n=200)
    rolling = reg.run_rolling_regression(excess, factors, window=60)

    assert rolling["available"] is True
    assert rolling["observations"] == 200 - 60 + 1
    assert len(rolling["dates"]) == rolling["observations"]
    for factor in reg.FACTOR_COLUMNS:
        assert len(rolling["betas"][factor]) == rolling["observations"]
    assert len(rolling["alpha_annualized"]) == rolling["observations"]
    assert len(rolling["r_squared"]) == rolling["observations"]
    json.dumps(rolling)


def test_rolling_returns_empty_when_history_shorter_than_window():
    excess, factors = _synthetic(n=40)
    rolling = reg.run_rolling_regression(excess, factors, window=126)
    assert rolling["available"] is False
    assert rolling["observations"] == 0
    assert rolling["dates"] == []
    assert rolling["betas"]["Mkt-RF"] == []

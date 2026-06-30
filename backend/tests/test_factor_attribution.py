"""Tests for the return-attribution waterfall (offline, synthetic data).

The defining property: the per-factor contributions plus alpha must add back to
the total excess return (the OLS-with-intercept identity). These tests pin that
reconciliation and the structure of the waterfall.
"""

import json

import numpy as np
import pandas as pd
import pytest

from backend.app.factors import regression as reg
from backend.app.factors.attribution import _share, build_attribution


def _fit(n=300, seed=11):
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2020-01-01", periods=n)
    factors = pd.DataFrame(
        {col: rng.normal(0.0004, 0.01, n) for col in reg.FACTOR_COLUMNS}, index=dates
    )
    factors["RF"] = 0.0001
    betas = np.array([1.1, 0.3, -0.2, 0.1, -0.05, 0.2])
    excess = 0.0002 + factors[reg.FACTOR_COLUMNS].values @ betas + rng.normal(0, 0.002, n)
    return reg.fit_factor_model(pd.Series(excess, index=dates, name="excess"), factors)


def test_waterfall_components_present_and_ordered():
    attribution = build_attribution(_fit())
    factors = [c["factor"] for c in attribution["components"]]
    assert factors == reg.FACTOR_COLUMNS + ["alpha"]
    alpha_component = attribution["components"][-1]
    assert alpha_component["factor"] == "alpha"
    assert alpha_component["beta"] is None


def test_waterfall_reconciles_to_total():
    attribution = build_attribution(_fit())
    # The true (full-precision) residual is ~0; the displayed slices, each rounded
    # to 6 dp independently, sum to the total within the rounding floor (~1e-6).
    assert attribution["residual_annualized"] == pytest.approx(0.0, abs=1e-9)
    reassembled = (
        attribution["explained_by_factors_annualized"] + attribution["alpha_annualized"]
    )
    assert reassembled == pytest.approx(attribution["total_excess_return_annualized"], abs=1e-5)


def test_component_contribution_equals_beta_times_factor_return():
    attribution = build_attribution(_fit())
    for component in attribution["components"][:-1]:  # skip the alpha slice
        expected = component["beta"] * component["factor_avg_return_annualized"]
        assert component["contribution_annualized"] == pytest.approx(expected, abs=1e-5)


def test_attribution_alpha_matches_full_sample_alpha():
    fit = _fit()
    attribution = build_attribution(fit)
    summary = reg.summarize_regression(fit)
    assert attribution["alpha_annualized"] == summary["alpha"]["annualized"]


def test_attribution_is_json_native():
    json.dumps(build_attribution(_fit()))


def test_share_returns_none_for_negligible_total():
    assert _share(0.01, 0.0) is None
    assert _share(0.05, 0.10) == pytest.approx(50.0)

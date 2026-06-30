"""Return attribution — the waterfall from factor tilts to total return.

Decomposes the portfolio's average excess return into one slice per factor plus
a residual alpha slice:

    avg(excess) = alpha + Σ_i  beta_i · avg(factor_i)
                  └ idiosyncratic ┘   └ contribution of factor i ┘

For an OLS fit *with an intercept* this identity is exact — the regression
residuals average to zero — so the slices add back to the total. That is what
makes the waterfall honest rather than an approximation. Daily averages are
annualized (× 252 trading days) so the numbers read in familiar "return per
year" terms. The attribution reads coefficients and means straight off the
shared `FactorFit` (full precision), so the only gap between the slices and the
total is sub-rounding noise (reported as `residual_annualized`).
"""

from .regression import (
    FACTOR_LABELS,
    TRADING_DAYS_PER_YEAR,
    FactorFit,
)

# Below this magnitude a "% of total" share is meaningless (near-zero total).
_MIN_TOTAL_FOR_SHARE = 1e-9


def _share(contribution: float, total: float) -> float | None:
    if abs(total) < _MIN_TOTAL_FOR_SHARE:
        return None
    return round(contribution / total * 100.0, 2)


def build_attribution(fit: FactorFit) -> dict:
    """Build the annualized attribution waterfall from a fitted factor model.

    Each factor's contribution is `beta_i · avg(factor_i)` annualized; alpha is
    the idiosyncratic slice (the fitted intercept, annualized). `components` is
    ordered factors-then-alpha and every number is an annualized decimal return.
    """
    params = fit.model.params
    factor_columns = list(fit.x.columns)

    total_annualized = float(fit.y.mean()) * TRADING_DAYS_PER_YEAR
    alpha_annualized = float(params["const"]) * TRADING_DAYS_PER_YEAR

    components = []
    explained_by_factors = 0.0
    for factor in factor_columns:
        beta = float(params[factor])
        factor_avg_annualized = float(fit.x[factor].mean()) * TRADING_DAYS_PER_YEAR
        contribution = beta * factor_avg_annualized
        explained_by_factors += contribution
        components.append(
            {
                "factor": factor,
                "label": FACTOR_LABELS.get(factor, factor),
                "beta": round(beta, 6),
                "factor_avg_return_annualized": round(factor_avg_annualized, 6),
                "contribution_annualized": round(contribution, 6),
                "pct_of_total": _share(contribution, total_annualized),
            }
        )

    # Alpha as the final slice of the waterfall (idiosyncratic / unexplained).
    components.append(
        {
            "factor": "alpha",
            "label": "Alpha (idiosyncratic)",
            "beta": None,
            "factor_avg_return_annualized": None,
            "contribution_annualized": round(alpha_annualized, 6),
            "pct_of_total": _share(alpha_annualized, total_annualized),
        }
    )

    residual = total_annualized - (explained_by_factors + alpha_annualized)

    return {
        "basis": "annualized_excess_return",
        "total_excess_return_annualized": round(total_annualized, 6),
        "explained_by_factors_annualized": round(explained_by_factors, 6),
        "alpha_annualized": round(alpha_annualized, 6),
        "residual_annualized": round(residual, 9),
        "components": components,
    }

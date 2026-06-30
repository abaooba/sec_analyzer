"""Factor exposure & performance attribution.

A self-contained analytics package that answers the question every PM and
allocator asks: *is this return alpha, or just factor beta?* Given a portfolio
(or a single stock/ETF), it decomposes the return stream against the
Fama-French 5-factor + Momentum model and reports:

  - static (full-sample) factor betas + alpha, with significance,
  - rolling betas (how the exposures drift over time),
  - a return-attribution waterfall (how much of the return came from market vs.
    size vs. value vs. ... vs. the portfolio's own idiosyncratic edge).

This is its own dimension of analysis (price/return based), separate from the
SEC-filing pipeline in `opinion.py`. The public entry point is
`analyze_factor_exposure`, surfaced via the `/factor-attribution` API endpoint.
"""

from .service import analyze_factor_exposure

__all__ = ["analyze_factor_exposure"]

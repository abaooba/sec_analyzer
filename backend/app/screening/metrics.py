"""Per-company screening metrics — the pure math, no database.

Every function here takes plain snapshot dicts (a "current" fiscal year and,
where the metric is year-over-year, a "prior" one) plus an optional market cap,
and returns numbers. Keeping the formulas free of I/O means the whole battery is
unit-tested against hand-computed values — the DB-backed entry point
`compute_company_metrics` just fetches the snapshots and delegates here.

The five metric families:
  - Piotroski F-Score  : 9 binary fundamental-momentum tests (0-9)
  - Altman Z-Score     : distress model (classic w/ market cap, else book Z'')
  - Sloan accruals     : (net income - operating cash flow) / avg assets
  - ROIC               : NOPAT / invested capital
  - FCF yield          : free cash flow / market cap

A snapshot dict uses the keys produced by `fundamentals_history.annual_fundamentals`
(revenue, net_income, assets, current_assets, current_liabilities, liabilities,
equity, retained_earnings, operating_cash_flow, capex, operating_income,
gross_profit, cost_of_revenue, long_term_debt, diluted_shares, income_tax,
pretax_income, period_end). Any field may be None; every formula degrades to None
rather than raising.
"""

from ..fundamentals_history import annual_fundamentals

# Effective tax rate is clamped to this band (and defaulted mid-band) so a freak
# ratio — a tax benefit, a near-zero pre-tax base — can't blow up NOPAT for ROIC.
DEFAULT_TAX_RATE = 0.21
MAX_TAX_RATE = 0.35

# Altman distress-zone cut points differ by model (see `_altman_zone`).
CLASSIC_ZONES = {"safe": 2.99, "distress": 1.81}
Z2PRIME_ZONES = {"safe": 2.6, "distress": 1.1}

# A Sloan accrual ratio above this is treated as an absolute earnings-quality
# red flag regardless of where the peer group sits (ranking may also flag the
# cross-sectional worst quartile).
ACCRUALS_RISK_THRESHOLD = 0.10


def _num(value):
    """Coerce to float, or None if it isn't a finite number."""
    if value is None:
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    # Reject NaN/inf so downstream comparisons stay well-defined.
    if result != result or result in (float("inf"), float("-inf")):
        return None
    return result


def _safe_div(numerator, denominator):
    """Divide, returning None on missing operands or a zero denominator."""
    numerator = _num(numerator)
    denominator = _num(denominator)
    if numerator is None or denominator is None or denominator == 0:
        return None
    return numerator / denominator


def free_cash_flow(snapshot: dict):
    """Operating cash flow minus capex. abs(capex) because filers sign it either way."""
    ocf = _num(snapshot.get("operating_cash_flow"))
    capex = _num(snapshot.get("capex"))
    if ocf is None or capex is None:
        return None
    return ocf - abs(capex)


def total_liabilities(snapshot: dict):
    """Total liabilities as reported, else derived from the accounting identity.

    Many filers (e.g. Coca-Cola) never tag `us-gaap:Liabilities` — they report
    only the current/non-current components. When the total is missing we fall
    back to assets - equity, which is the balance-sheet identity (a hair high when
    there's minority interest, but the standard, robust substitute). Altman needs
    a liabilities figure, so this keeps those names scorable instead of blank.
    """
    liabilities = _num(snapshot.get("liabilities"))
    if liabilities is not None:
        return liabilities
    assets = _num(snapshot.get("assets"))
    equity = _num(snapshot.get("equity"))
    if assets is None or equity is None:
        return None
    return assets - equity


def gross_profit_value(snapshot: dict):
    """Gross profit as reported, else revenue - cost of revenue, else None."""
    gross = _num(snapshot.get("gross_profit"))
    if gross is not None:
        return gross
    revenue = _num(snapshot.get("revenue"))
    cost = _num(snapshot.get("cost_of_revenue"))
    if revenue is None or cost is None:
        return None
    return revenue - cost


# --- Piotroski F-Score -----------------------------------------------------

def compute_piotroski(current: dict, prior: dict) -> dict:
    """The 9 Piotroski binary tests, scored 0-9 (one point per pass).

    Tests span three themes — profitability (1-4), leverage/liquidity/funding
    (5-7), and operating efficiency (8-9). Each test is True (pass, 1 point),
    False (fail, 0), or None (inputs missing — not counted, and it lowers
    `tests_available` so a data-thin F-Score isn't mistaken for a genuine 0).
    """
    prior = prior or {}

    # Return on assets, end-of-year basis, used for tests 1 and 3 consistently.
    roa_curr = _safe_div(current.get("net_income"), current.get("assets"))
    roa_prior = _safe_div(prior.get("net_income"), prior.get("assets"))

    ocf_curr = _num(current.get("operating_cash_flow"))
    ni_curr = _num(current.get("net_income"))

    # Leverage = long-term debt / assets (lower is better -> a decrease passes).
    lev_curr = _safe_div(current.get("long_term_debt"), current.get("assets"))
    lev_prior = _safe_div(prior.get("long_term_debt"), prior.get("assets"))

    curr_ratio_curr = _safe_div(current.get("current_assets"), current.get("current_liabilities"))
    curr_ratio_prior = _safe_div(prior.get("current_assets"), prior.get("current_liabilities"))

    shares_curr = _num(current.get("diluted_shares"))
    shares_prior = _num(prior.get("diluted_shares"))

    gm_curr = _safe_div(gross_profit_value(current), current.get("revenue"))
    gm_prior = _safe_div(gross_profit_value(prior), prior.get("revenue"))

    turnover_curr = _safe_div(current.get("revenue"), current.get("assets"))
    turnover_prior = _safe_div(prior.get("revenue"), prior.get("assets"))

    def gt(a, b):
        """a > b, or None if either side is missing."""
        return None if a is None or b is None else a > b

    tests = {
        # Profitability
        "roa_positive": None if roa_curr is None else roa_curr > 0,
        "cfo_positive": None if ocf_curr is None else ocf_curr > 0,
        "roa_improving": gt(roa_curr, roa_prior),
        "accrual_quality": gt(ocf_curr, ni_curr),  # cash beats accounting profit
        # Leverage / liquidity / source of funds
        "leverage_decreasing": None if lev_curr is None or lev_prior is None else lev_curr < lev_prior,
        "current_ratio_increasing": gt(curr_ratio_curr, curr_ratio_prior),
        "no_new_shares": None if shares_curr is None or shares_prior is None else shares_curr <= shares_prior,
        # Operating efficiency
        "gross_margin_increasing": gt(gm_curr, gm_prior),
        "asset_turnover_increasing": gt(turnover_curr, turnover_prior),
    }

    passed = sum(1 for v in tests.values() if v is True)
    available = sum(1 for v in tests.values() if v is not None)

    return {
        "f_score": passed,
        "tests": tests,
        "tests_available": available,
        "complete": available == len(tests),
    }


# --- Altman Z-Score --------------------------------------------------------

def _altman_zone(z, zones: dict) -> str:
    """Map a Z value to a distress zone using the model-appropriate cut points."""
    if z is None:
        return "unknown"
    if z >= zones["safe"]:
        return "safe"
    if z < zones["distress"]:
        return "distress"
    return "grey"


def compute_altman(current: dict, market_cap=None) -> dict:
    """Altman Z-Score with the right model for the data on hand.

    With a market cap we use the *classic* five-factor Z (equity at market value
    in X4); without one we fall back to Altman's Z'' ("double-prime") book-value
    model, which drops the sales/assets term and is the accepted cross-sector /
    private-company variant. The returned `zone` (safe/grey/distress) uses each
    model's own thresholds, so "distress" means the same thing either way.
    """
    assets = _num(current.get("assets"))
    liabilities = total_liabilities(current)  # reported, or derived (assets - equity)
    if assets is None or assets == 0 or liabilities is None or liabilities == 0:
        return {"z_score": None, "model": None, "zone": "unknown", "components": {}}

    working_capital = None
    ca = _num(current.get("current_assets"))
    cl = _num(current.get("current_liabilities"))
    if ca is not None and cl is not None:
        working_capital = ca - cl

    x1 = _safe_div(working_capital, assets)                       # liquidity
    x2 = _safe_div(current.get("retained_earnings"), assets)     # cumulative profitability
    x3 = _safe_div(current.get("operating_income"), assets)      # operating productivity (EBIT/TA)
    x5 = _safe_div(current.get("revenue"), assets)               # asset turnover

    market_cap = _num(market_cap)
    if market_cap is not None and market_cap > 0:
        x4 = _safe_div(market_cap, liabilities)                  # market value of equity / liabilities
        components = {"x1": x1, "x2": x2, "x3": x3, "x4": x4, "x5": x5}
        # Classic Z needs all five factors; a missing one makes the score meaningless.
        if any(v is None for v in components.values()):
            return {"z_score": None, "model": "classic", "zone": "unknown", "components": components}
        z = 1.2 * x1 + 1.4 * x2 + 3.3 * x3 + 0.6 * x4 + 1.0 * x5
        return {
            "z_score": round(z, 3),
            "model": "classic",
            "zone": _altman_zone(z, CLASSIC_ZONES),
            "components": components,
        }

    # No market cap -> book-value Z'' (no X5 term; X4 uses book equity).
    x4 = _safe_div(current.get("equity"), liabilities)
    components = {"x1": x1, "x2": x2, "x3": x3, "x4": x4}
    if any(v is None for v in components.values()):
        return {"z_score": None, "model": "z_double_prime", "zone": "unknown", "components": components}
    z = 6.56 * x1 + 3.26 * x2 + 6.72 * x3 + 1.05 * x4
    return {
        "z_score": round(z, 3),
        "model": "z_double_prime",
        "zone": _altman_zone(z, Z2PRIME_ZONES),
        "components": components,
    }


# --- Sloan accruals (earnings quality) -------------------------------------

def compute_accruals(current: dict, prior: dict) -> float | None:
    """Balance-sheet-neutral Sloan accrual ratio: (net income - CFO) / avg assets.

    High *positive* accruals mean reported earnings run well ahead of the cash
    actually generated — the classic earnings-quality warning. Negative accruals
    (cash exceeds earnings) are conservative and benign. Average assets smooths a
    year of heavy asset growth; it falls back to current assets if there's no prior.
    """
    ni = _num(current.get("net_income"))
    ocf = _num(current.get("operating_cash_flow"))
    if ni is None or ocf is None:
        return None

    assets_curr = _num(current.get("assets"))
    assets_prior = _num((prior or {}).get("assets"))
    if assets_curr is None:
        return None
    avg_assets = assets_curr if assets_prior is None else (assets_curr + assets_prior) / 2
    if avg_assets == 0:
        return None

    return (ni - ocf) / avg_assets


# --- ROIC ------------------------------------------------------------------

def effective_tax_rate(current: dict) -> float:
    """Income tax / pre-tax income, clamped to [0, MAX_TAX_RATE].

    Defaults to DEFAULT_TAX_RATE when the ratio is unavailable or nonsensical
    (a pre-tax loss, a net tax benefit) so NOPAT stays economically sensible.
    """
    tax = _num(current.get("income_tax"))
    pretax = _num(current.get("pretax_income"))
    if tax is None or pretax is None or pretax <= 0:
        return DEFAULT_TAX_RATE
    rate = tax / pretax
    if rate < 0:
        return DEFAULT_TAX_RATE
    return min(rate, MAX_TAX_RATE)


def compute_roic(current: dict) -> dict:
    """Return on invested capital = NOPAT / invested capital.

    NOPAT = EBIT * (1 - effective tax rate), with operating income standing in
    for EBIT. Invested capital is the book sum of equity and long-term debt — the
    capital the operating assets are financed with. None when that base is
    missing or non-positive (ROIC is meaningless on negative capital).
    """
    ebit = _num(current.get("operating_income"))
    equity = _num(current.get("equity"))
    debt = _num(current.get("long_term_debt")) or 0.0

    if ebit is None or equity is None:
        return {"roic": None, "nopat": None, "invested_capital": None, "tax_rate": None}

    tax_rate = effective_tax_rate(current)
    nopat = ebit * (1 - tax_rate)
    invested_capital = equity + debt
    if invested_capital <= 0:
        return {"roic": None, "nopat": nopat, "invested_capital": invested_capital, "tax_rate": tax_rate}

    return {
        "roic": nopat / invested_capital,
        "nopat": nopat,
        "invested_capital": invested_capital,
        "tax_rate": tax_rate,
    }


# --- FCF yield (value) -----------------------------------------------------

def compute_fcf_yield(current: dict, market_cap=None) -> dict:
    """Free-cash-flow yield and earnings yield against market cap.

    FCF yield = FCF / market cap is the screen's value axis: a high yield means
    the market is paying little for each dollar of cash the business throws off.
    Both yields are None without a positive market cap (there is no "value" read
    without a price)."""
    fcf = free_cash_flow(current)
    market_cap = _num(market_cap)

    if market_cap is None or market_cap <= 0:
        return {"fcf": fcf, "fcf_yield": None, "earnings_yield": None}

    ni = _num(current.get("net_income"))
    return {
        "fcf": fcf,
        "fcf_yield": None if fcf is None else fcf / market_cap,
        "earnings_yield": None if ni is None else ni / market_cap,
    }


# --- Per-company bundle ----------------------------------------------------

def compute_metrics_from_snapshots(
    current: dict,
    prior: dict | None,
    *,
    market_cap=None,
    ticker: str = "",
    name: str = "",
    cik: str = "",
) -> dict:
    """Assemble the full metric bundle for one company from its two snapshots."""
    prior = prior or {}

    piotroski = compute_piotroski(current, prior)
    altman = compute_altman(current, market_cap=market_cap)
    accruals = compute_accruals(current, prior)
    roic = compute_roic(current)
    yields = compute_fcf_yield(current, market_cap=market_cap)

    return {
        "ticker": ticker,
        "name": name,
        "cik": cik,
        "period_end": current.get("period_end"),
        "prior_period_end": prior.get("period_end"),
        "market_cap": _num(market_cap),
        # Headline metrics (flat, for ranking + table columns).
        "f_score": piotroski["f_score"],
        "f_score_available": piotroski["tests_available"],
        "altman_z": altman["z_score"],
        "altman_model": altman["model"],
        "distress_zone": altman["zone"],
        "accruals": accruals,
        "roic": roic["roic"],
        "fcf_yield": yields["fcf_yield"],
        "earnings_yield": yields["earnings_yield"],
        # Full detail (for the report / API consumers / LLM).
        "detail": {
            "piotroski": piotroski,
            "altman": altman,
            "roic": roic,
            "fcf": yields["fcf"],
            "current": current,
            "prior": prior,
        },
    }


def compute_company_metrics(
    cik: str,
    *,
    ticker: str = "",
    name: str = "",
    market_cap=None,
) -> dict | None:
    """DB-backed entry point: pull the two latest annual snapshots and score them.

    Returns None if the company has no annual fundamentals on hand (nothing to
    screen). A single year still scores — the year-over-year tests just come back
    as not-available rather than failing.
    """
    normalized_cik = str(cik).zfill(10)
    history = annual_fundamentals(normalized_cik, max_years=2)
    if not history:
        return None

    current = history[0]
    prior = history[1] if len(history) > 1 else {}
    return compute_metrics_from_snapshots(
        current,
        prior,
        market_cap=market_cap,
        ticker=ticker,
        name=name,
        cik=normalized_cik,
    )

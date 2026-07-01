"""Orchestrate the screen: resolve tickers -> ingest facts -> rank -> assemble.

This is the one place with side effects. It resolves each ticker to a CIK, makes
sure the company's XBRL facts are in the DB (a light, facts-only ingest — no
filing HTML, since the screen is purely numeric), fetches market caps best-effort,
computes every company's metrics, ranks them cross-sectionally, and returns a
single JSON-serializable dict.

That returned dict is intentionally a *superset* of the `rank_screen` structure
(same `rows` / `universe_size` / `medians` / `flag_counts` keys) so the CLI can
hand it straight to `render.render_screen_table` / `render_scatter_ascii`, while
the API adds per-row `colors` and ready-to-plot `scatter` points on top.
"""

import logging

from ..company_lookup import find_company_match
from ..fundamentals import ingest_company_facts
from .market_data import get_market_caps
from .metrics import compute_company_metrics
from .ranking import rank_screen
from .render import row_colors, scatter_points

logger = logging.getLogger(__name__)

# Soft cap so a runaway request can't fan out into hundreds of SEC downloads.
MAX_UNIVERSE = 60


def _normalize_tickers(tickers: list[str]) -> list[str]:
    """Upper-case, strip, and de-dupe tickers while preserving order."""
    seen: set[str] = set()
    result: list[str] = []
    for raw in tickers:
        ticker = (raw or "").strip().upper()
        if ticker and ticker not in seen:
            seen.add(ticker)
            result.append(ticker)
    return result


def resolve_universe(tickers: list[str]) -> tuple[list[dict], list[str]]:
    """Resolve tickers to {ticker, cik, name} records; return (resolved, unresolved)."""
    resolved: list[dict] = []
    unresolved: list[str] = []
    for ticker in tickers:
        match = find_company_match(ticker, ticker)
        if not match:
            unresolved.append(ticker)
            continue
        resolved.append(
            {"ticker": ticker, "cik": match["cik"], "name": match.get("company_name", ticker)}
        )
    return resolved, unresolved


def run_screen(
    tickers: list[str],
    *,
    ingest: bool = True,
    fetch_market_caps: bool = True,
) -> dict:
    """Screen `tickers` and return the ranked, flagged, plot-ready result.

    `ingest=False` skips the SEC facts download (assumes the DB is already
    populated — used by tests and repeat runs); `fetch_market_caps=False` skips
    the yfinance call (the screen then falls back to book-value Altman and reports
    no FCF yield). Companies that can't be resolved or have no annual fundamentals
    are reported in `unresolved` / `no_data` rather than silently dropped.
    """
    tickers = _normalize_tickers(tickers)
    truncated = tickers[MAX_UNIVERSE:]
    tickers = tickers[:MAX_UNIVERSE]
    if truncated:
        logger.warning("Universe capped at %d; dropped: %s", MAX_UNIVERSE, ", ".join(truncated))

    resolved, unresolved = resolve_universe(tickers)

    # Make sure each company's XBRL facts are on hand (idempotent, de-duped).
    if ingest:
        for company in resolved:
            try:
                ingest_company_facts(company["cik"])
            except Exception as exc:  # a single bad download shouldn't sink the screen
                logger.warning("Facts ingest failed for %s (%s): %s", company["ticker"], company["cik"], exc)

    # Market caps power FCF yield + the classic Altman model (best-effort).
    market_caps: dict[str, float] = {}
    if fetch_market_caps and resolved:
        market_caps = get_market_caps([c["ticker"] for c in resolved])

    metrics_list: list[dict] = []
    no_data: list[str] = []
    for company in resolved:
        bundle = compute_company_metrics(
            company["cik"],
            ticker=company["ticker"],
            name=company["name"],
            market_cap=market_caps.get(company["ticker"]),
        )
        if bundle is None:
            no_data.append(company["ticker"])
            continue
        metrics_list.append(bundle)

    ranked = rank_screen(metrics_list)

    # Attach per-row color names (the API's coloring hook for the UI).
    for row in ranked["rows"]:
        row["colors"] = row_colors(row)

    # A superset of `ranked`: same keys the renderers read, plus API extras.
    response = {
        "universe": tickers,
        "universe_size": ranked["universe_size"],
        "screened": ranked["universe_size"],
        "unresolved": unresolved,
        "no_data": no_data,
        "truncated": truncated,
        "flag_counts": ranked["flag_counts"],
        "medians": ranked["medians"],
        "rows": ranked["rows"],
        "scatter": {
            "x_label": "Value (FCF-yield percentile)",
            "y_label": "Quality (F-Score / ROIC / low accruals)",
            "median_value": ranked["medians"]["value_score"],
            "median_quality": ranked["medians"]["quality_score"],
            "points": scatter_points(ranked),
        },
    }
    return response

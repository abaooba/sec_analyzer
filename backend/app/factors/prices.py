"""Portfolio returns from market prices (the regression's left-hand side).

Turns a set of holdings (tickers + weights) into a single daily return series:
download adjusted prices, convert to daily simple returns, and combine them by
weight into one portfolio stream.

`yfinance` is the price source, imported *lazily* inside the downloader so that
(a) app startup never pays its slow import, and (b) the offline test suite — which
substitutes synthetic prices — never needs it installed. Everything below the
download is pure pandas, so the return/aggregation math is unit-tested without a
network.
"""

import logging

import pandas as pd

logger = logging.getLogger(__name__)


def download_adjusted_prices(
    tickers: list[str], start: str | None = None, end: str | None = None
) -> pd.DataFrame:
    """Download split/dividend-adjusted daily closes for `tickers`.

    Returns a DataFrame indexed by date with one column per ticker that actually
    returned data (unknown/typo'd tickers come back all-NaN and are dropped).
    Network-touching — tests monkeypatch this and pass synthetic prices instead.
    """
    import yfinance as yf  # lazy: keep the heavy import off the startup/test path

    # Always hand yfinance a list so the "Close" selection yields a DataFrame
    # (ticker-keyed columns) rather than a bare Series for the single-ticker case.
    raw = yf.download(
        list(tickers),
        start=start,
        end=end,
        auto_adjust=True,  # "Close" is then the adjusted close
        progress=False,
        group_by="column",
    )

    close = raw["Close"] if "Close" in raw.columns.get_level_values(0) else raw
    if isinstance(close, pd.Series):
        close = close.to_frame(tickers[0])

    # Keep only requested tickers that came back with at least one real price.
    available = [t for t in tickers if t in close.columns and close[t].notna().any()]
    missing = [t for t in tickers if t not in available]
    if missing:
        logger.warning("No price data returned for: %s", ", ".join(missing))
    return close[available]


def prices_to_returns(prices: pd.DataFrame) -> pd.DataFrame:
    """Daily simple returns from a price panel.

    Uses pct_change with no forward-filling (pandas's default since 3.0), so a
    genuine price gap stays NaN instead of being silently carried forward, and
    drops the leading all-NaN row that pct_change always produces.
    """
    returns = prices.pct_change()
    return returns.dropna(how="all")


def build_portfolio_returns(returns: pd.DataFrame, weights: dict[str, float]) -> pd.Series:
    """Combine per-ticker returns into one weighted portfolio return series.

    Only tickers present in `returns` are used; their weights are renormalized to
    sum to 1 (so a portfolio still makes sense if some tickers had no data). Days
    where any held ticker is missing a return are dropped, so every portfolio
    observation is a like-for-like weighted basket.
    """
    present = [ticker for ticker in weights if ticker in returns.columns]
    if not present:
        raise ValueError("None of the requested tickers have return data")

    total_weight = sum(weights[ticker] for ticker in present)
    if total_weight <= 0:
        raise ValueError("Portfolio weights must sum to a positive number")

    normalized = pd.Series({ticker: weights[ticker] / total_weight for ticker in present})
    aligned = returns[present].dropna(how="any")
    portfolio = aligned.mul(normalized, axis=1).sum(axis=1)
    portfolio.name = "portfolio"
    return portfolio

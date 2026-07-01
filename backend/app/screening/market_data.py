"""Market caps for the screen's value axis — the only network-touching piece.

FCF yield and the classic Altman Z need a market value of equity, which XBRL
doesn't carry. We source it from `yfinance`, imported *lazily* inside the fetch
(exactly like `factors/prices.py`) so app startup never pays the slow import and
the offline test suite never needs it installed — tests monkeypatch
`get_market_caps` with canned values.

Everything here is best-effort: a ticker yfinance can't price simply comes back
missing, and the screen degrades that name to book-value Altman with no FCF yield
rather than failing the whole run.
"""

import logging

logger = logging.getLogger(__name__)


def get_market_caps(tickers: list[str]) -> dict[str, float]:
    """Return {ticker: market_cap} for the tickers yfinance can price.

    Missing/typo'd tickers and any that error out are simply omitted from the
    result (logged, not raised). Network-touching — tests replace this wholesale.
    """
    if not tickers:
        return {}

    try:
        import yfinance as yf  # lazy: keep the heavy import off the startup/test path
    except ImportError:
        logger.warning("yfinance not installed; screen will run without market caps.")
        return {}

    caps: dict[str, float] = {}
    for ticker in tickers:
        try:
            info = yf.Ticker(ticker).info or {}
            cap = info.get("marketCap")
            if cap:
                caps[ticker] = float(cap)
            else:
                logger.warning("No market cap returned for %s.", ticker)
        except Exception as exc:  # one bad ticker shouldn't sink the batch
            logger.warning("Failed to fetch market cap for %s: %s", ticker, exc)

    return caps

"""FastAPI web layer — exposes the analyzer as a single HTTP endpoint.

Run with: `uvicorn backend.api:app --reload`
Then POST {"company_name": "Apple", "ticker": "AAPL"} to /analyze.

This file is deliberately thin: it just wires an HTTP request to the same
pipeline the CLI (main.py) uses — lookup -> ingest filings -> ingest facts ->
build opinion -> clean up. All the real work lives in backend/app/.
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from backend.app.config import settings
from backend.app.db import init_db
from backend.app.company_lookup import find_company_match
from backend.app.ingest import ingest_company, delete_local_filings_for_company
from backend.app.fundamentals import ingest_company_facts
from backend.app.opinion import build_full_opinion

app = FastAPI()

# CORS middleware — lets a browser frontend on a different origin call this API.
# Origins come from settings.cors_allow_origins (env CORS_ALLOW_ORIGINS); it
# defaults to "*" (any site) for dev — set an allowlist to lock down in prod.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_allow_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

class AnalyzeRequest(BaseModel):
    """Request body schema; FastAPI validates incoming JSON against this."""
    company_name: str
    ticker: str | None = None


class Holding(BaseModel):
    """One position in a portfolio: a ticker and its weight (default 1.0)."""
    ticker: str
    weight: float = 1.0


class ScreenRequest(BaseModel):
    """Request body for /screen: a universe of tickers to rank cross-sectionally.

    `ingest` (default true) downloads each company's XBRL facts before scoring;
    set false to screen only what's already in the DB. `fetch_market_caps`
    (default true) pulls market caps for FCF yield + the classic Altman model.
    """
    tickers: list[str]
    ingest: bool = True
    fetch_market_caps: bool = True


class FactorAttributionRequest(BaseModel):
    """Request body for /factor-attribution.

    Supply either a list of `holdings` (a portfolio) or a single `ticker` (a
    stock/ETF, treated as a 100% position). `start_date` / `end_date` are ISO
    dates (default: the last few years); `rolling_window` is the rolling-beta
    window in trading days.
    """
    holdings: list[Holding] | None = None
    ticker: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    rolling_window: int = 126

@app.post("/analyze")
def analyze(req: AnalyzeRequest):
    """Resolve the company, run the full pipeline, and return the opinion JSON."""
    init_db()  # ensure tables exist (idempotent)
    match = find_company_match(req.company_name, req.ticker)
    if not match:
        return {"error": f"Could not find company: {req.company_name}"}

    cik = match["cik"]
    company_name = match["company_name"]
    ticker = req.ticker or match.get("ticker", "")

    try:
        ingest_company(cik)          # download filings -> DB + disk cache
        ingest_company_facts(cik)    # download XBRL financial facts -> DB
        result = build_full_opinion(cik, company_name, ticker)
        return result  # FastAPI serializes the dict to a JSON response
    finally:
        # Always clear the on-disk HTML cache, even if analysis raised.
        delete_local_filings_for_company(cik)


@app.post("/screen")
def screen(req: ScreenRequest):
    """Rank a universe of tickers on Piotroski / Altman Z / accruals / ROIC / FCF
    yield, flag distress and earnings-quality risks, and return a plot-ready
    value-vs-quality result.

    Imported lazily so the screen's stack (and its optional yfinance market-cap
    fetch) stays off app startup and off the /analyze path — it loads only when
    this endpoint is actually hit.
    """
    from backend.app.screening.service import run_screen

    if not req.tickers:
        return {"error": "Provide a non-empty 'tickers' list."}

    init_db()  # ensure tables exist before the facts ingest writes to them
    return run_screen(
        req.tickers,
        ingest=req.ingest,
        fetch_market_caps=req.fetch_market_caps,
    )


@app.post("/factor-attribution")
def factor_attribution(req: FactorAttributionRequest):
    """Decompose a portfolio's (or single ticker's) returns against the
    Fama-French 5 + Momentum model: static + rolling factor betas, alpha, and a
    return-attribution waterfall.

    Imported lazily so the heavy quant stack (statsmodels / pandas / yfinance)
    stays off app startup and off the /analyze path — it loads only when this
    endpoint is actually hit.
    """
    from backend.app.factors.service import analyze_factor_exposure

    holdings = [holding.model_dump() for holding in (req.holdings or [])]
    if not holdings and req.ticker:
        holdings = [{"ticker": req.ticker, "weight": 1.0}]
    if not holdings:
        return {"error": "Provide either 'holdings' or a single 'ticker'."}

    return analyze_factor_exposure(
        holdings,
        start_date=req.start_date,
        end_date=req.end_date,
        rolling_window=req.rolling_window,
    )
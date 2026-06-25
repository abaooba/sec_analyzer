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
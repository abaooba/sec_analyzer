from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from backend.app.db import init_db
from backend.app.company_lookup import find_company_match
from backend.app.ingest import ingest_company, delete_local_filings_for_company
from backend.app.fundamentals import ingest_company_facts
from backend.app.opinion import build_full_opinion

app = FastAPI()

# This is the CORS middleware — it lets your frontend talk to your backend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # You can tighten this later
    allow_methods=["*"],
    allow_headers=["*"],
)

class AnalyzeRequest(BaseModel):
    company_name: str
    ticker: str | None = None

@app.post("/analyze")
def analyze(req: AnalyzeRequest):
    init_db()
    match = find_company_match(req.company_name)
    if not match:
        return {"error": f"Could not find company: {req.company_name}"}
    
    cik = match["cik"].zfill(10)
    company_name = match["title"]
    ticker = req.ticker or match.get("ticker", "")

    try:
        ingest_company(cik)
        ingest_company_facts(cik)
        result = build_full_opinion(cik, company_name, ticker)
        return result
    finally:
        delete_local_filings_for_company(cik)
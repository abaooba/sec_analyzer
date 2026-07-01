"""Tests for the screen orchestrator (`run_screen`).

Two levels: a mocked control-flow test (resolution, no-data handling, arg
plumbing) and an integration test that seeds a real in-memory DB and runs the
genuine metric/rank pipeline through the service — only the network edges
(company lookup, market caps) are stubbed.
"""

from backend.app.models import CompanyFact
from backend.app.screening import service


# Field -> (XBRL tag, unit) used to seed a company's annual facts.
_FIELD_TAG = {
    "revenue": ("Revenues", "USD"),
    "net_income": ("NetIncomeLoss", "USD"),
    "assets": ("Assets", "USD"),
    "current_assets": ("AssetsCurrent", "USD"),
    "current_liabilities": ("LiabilitiesCurrent", "USD"),
    "liabilities": ("Liabilities", "USD"),
    "equity": ("StockholdersEquity", "USD"),
    "retained_earnings": ("RetainedEarningsAccumulatedDeficit", "USD"),
    "operating_cash_flow": ("NetCashProvidedByUsedInOperatingActivities", "USD"),
    "capex": ("PaymentsToAcquirePropertyPlantAndEquipment", "USD"),
    "operating_income": ("OperatingIncomeLoss", "USD"),
    "gross_profit": ("GrossProfit", "USD"),
    "long_term_debt": ("LongTermDebtNoncurrent", "USD"),
    "diluted_shares": ("WeightedAverageNumberOfDilutedSharesOutstanding", "shares"),
    "income_tax": ("IncomeTaxExpenseBenefit", "USD"),
    "pretax_income": (
        "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
        "USD",
    ),
}


def _facts_for(cik, snapshot, end_date, filed):
    facts = []
    for field, value in snapshot.items():
        if field not in _FIELD_TAG or value is None:
            continue
        tag, unit = _FIELD_TAG[field]
        facts.append(
            CompanyFact(
                cik=cik, taxonomy="us-gaap", tag=tag, unit=unit,
                fiscal_year=2024, fiscal_period="FY", form="10-K",
                filed=filed, end_date=end_date, value=value,
            )
        )
    return facts


def _seed_company(session_factory, cik, current, prior):
    with session_factory() as session:
        session.add_all(_facts_for(cik, current, "2024-12-31", "2025-02-01"))
        session.add_all(_facts_for(cik, prior, "2023-12-31", "2024-02-01"))
        session.commit()


# --- control flow (mocked) -------------------------------------------------

def test_run_screen_reports_unresolved_and_no_data(monkeypatch):
    # GOOD resolves and has metrics; GHOST resolves but yields no data; NOPE fails lookup.
    monkeypatch.setattr(
        service, "find_company_match",
        lambda name, ticker=None: None if ticker == "NOPE"
        else {"cik": ticker.lower(), "company_name": f"{ticker} Inc"},
    )
    monkeypatch.setattr(service, "get_market_caps", lambda tickers: {})
    monkeypatch.setattr(
        service, "compute_company_metrics",
        lambda cik, *, ticker, name, market_cap: None if ticker == "GHOST"
        else dict(ticker=ticker, name=name, cik=cik, f_score=7, altman_z=3.0,
                  distress_zone="safe", accruals=0.0, roic=0.12, fcf_yield=0.04),
    )

    result = service.run_screen(["good", "ghost", "nope"], ingest=False, fetch_market_caps=False)
    assert result["unresolved"] == ["NOPE"]
    assert result["no_data"] == ["GHOST"]
    assert [r["ticker"] for r in result["rows"]] == ["GOOD"]
    assert result["rows"][0]["colors"]["f_score"] == "green"  # colors attached for the UI


def test_run_screen_dedupes_and_uppercases(monkeypatch):
    seen = []
    monkeypatch.setattr(
        service, "find_company_match",
        lambda name, ticker=None: seen.append(ticker) or {"cik": ticker, "company_name": ticker},
    )
    monkeypatch.setattr(service, "get_market_caps", lambda tickers: {})
    monkeypatch.setattr(service, "compute_company_metrics",
                        lambda cik, *, ticker, name, market_cap: None)
    service.run_screen(["aapl", "AAPL", " msft "], ingest=False, fetch_market_caps=False)
    assert seen == ["AAPL", "MSFT"]  # de-duped + normalized, order preserved


# --- integration (real pipeline over a seeded DB) --------------------------

def test_run_screen_integration_ranks_and_flags(monkeypatch, patch_fundamentals_history_db):
    strong_cur = dict(
        revenue=1000, net_income=200, assets=2000, current_assets=900,
        current_liabilities=400, liabilities=900, equity=1100, retained_earnings=800,
        operating_cash_flow=260, capex=40, operating_income=300, gross_profit=500,
        long_term_debt=300, diluted_shares=100, income_tax=42, pretax_income=200,
    )
    strong_prior = dict(strong_cur, net_income=150, operating_cash_flow=200,
                        operating_income=240, revenue=900, assets=1900)
    # Distressed: negative retained earnings, thin equity, heavy liabilities, losses.
    distress_cur = dict(
        revenue=1000, net_income=-40, assets=2000, current_assets=500,
        current_liabilities=800, liabilities=1950, equity=50, retained_earnings=-500,
        operating_cash_flow=-10, capex=30, operating_income=-30, gross_profit=200,
        long_term_debt=900, diluted_shares=120, income_tax=0, pretax_income=-40,
    )
    distress_prior = dict(distress_cur, equity=90, net_income=-20)

    # Seed under 10-digit CIKs, exactly as the real lookup + ingest would store them.
    ciks = {"STRG": "0000000001", "DSTR": "0000000002"}
    _seed_company(patch_fundamentals_history_db, ciks["STRG"], strong_cur, strong_prior)
    _seed_company(patch_fundamentals_history_db, ciks["DSTR"], distress_cur, distress_prior)

    monkeypatch.setattr(
        service, "find_company_match",
        lambda name, ticker=None: {"cik": ciks[ticker], "company_name": f"{ticker} Inc"},
    )
    # Give both a market cap so FCF yield + classic Altman are exercised.
    monkeypatch.setattr(service, "get_market_caps", lambda tickers: {"STRG": 3000.0, "DSTR": 300.0})

    result = service.run_screen(["STRG", "DSTR"], ingest=False)

    assert result["universe_size"] == 2
    assert result["rows"][0]["ticker"] == "STRG"  # strong ranks first
    dstr = next(r for r in result["rows"] if r["ticker"] == "DSTR")
    assert "distress" in dstr["flags"]
    assert dstr["distress_zone"] == "distress"
    # Scatter points are built and colored for the plottable names.
    tickers_plotted = {p["ticker"] for p in result["scatter"]["points"]}
    assert tickers_plotted == {"STRG", "DSTR"}

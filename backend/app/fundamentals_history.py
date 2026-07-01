"""Assemble a clean *multi-year annual* financial history from XBRL facts.

`metrics.compute_basic_snapshot` only needs the single latest value of each line
item, but the screen's metrics (Piotroski, Altman Z, accruals) are year-over-year
by construction — they compare this fiscal year against last. This module builds
that per-year history.

The one subtlety that makes it correct: the SEC companyfacts `fy`/`fp` fields
label an observation with the *filing's* fiscal year, NOT the period the number
covers. A FY2025 10-K repeats the prior year's balance sheet tagged `fy=2025`, so
grouping by `fy` silently mixes periods (you can get 2022 equity labelled 2025).
The authoritative period key is `end_date`. So we group every annual-form fact by
`end_date` and, for each period, keep the value from the *latest* filing — which
also makes the series restatement-aware (a later 10-K's re-presented figure wins).
"""

from sqlalchemy import select

from .db import SessionLocal
from .metrics import CURRENCY_UNITS
from .models import CompanyFact

# Annual report forms only. Screening metrics are annual, so interim 10-Q/6-K
# facts are deliberately excluded — mixing a quarterly flow into a year-over-year
# comparison would corrupt every ratio.
ANNUAL_FORMS = ("10-K", "20-F", "40-F")

# Each screen field maps to the XBRL tag synonyms that express it, across the
# us-gaap and ifrs-full taxonomies. Order doesn't matter — a period takes the
# first synonym that has a value at that period end (see `annual_fact_series`).
FIELD_TAGS: dict[str, list[str]] = {
    "revenue": [
        "Revenues",
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "Revenue",
        "RevenueFromContractsWithCustomers",
    ],
    "net_income": ["NetIncomeLoss", "ProfitLoss"],
    "assets": ["Assets"],
    "current_assets": ["AssetsCurrent", "CurrentAssets"],
    "liabilities": ["Liabilities"],
    "current_liabilities": ["LiabilitiesCurrent", "CurrentLiabilities"],
    "equity": ["StockholdersEquity", "Equity", "EquityAttributableToOwnersOfParent"],
    "retained_earnings": ["RetainedEarningsAccumulatedDeficit", "RetainedEarnings"],
    "operating_cash_flow": [
        "NetCashProvidedByUsedInOperatingActivities",
        "CashFlowsFromUsedInOperatingActivities",
        "NetCashFlowsFromUsedInOperatingActivities",
    ],
    "capex": [
        "PaymentsToAcquirePropertyPlantAndEquipment",
        "PaymentsToAcquireProductiveAssets",  # NVIDIA / Ford et al. use this concept
        "PurchaseOfPropertyPlantAndEquipment",
        "PropertyPlantAndEquipmentAdditions",
    ],
    "operating_income": ["OperatingIncomeLoss", "OperatingProfitLoss"],  # EBIT proxy
    "gross_profit": ["GrossProfit"],
    "cost_of_revenue": ["CostOfRevenue", "CostOfGoodsAndServicesSold", "CostOfSales"],
    "long_term_debt": ["LongTermDebtNoncurrent", "BorrowingsNoncurrent", "NoncurrentBorrowings"],
    "diluted_shares": [
        "WeightedAverageNumberOfDilutedSharesOutstanding",
        "WeightedAverageNumberOfSharesOutstandingDiluted",
        "WeightedAverageNumberOfOrdinarySharesOutstandingDiluted",
    ],
    "income_tax": ["IncomeTaxExpenseBenefit", "IncomeTaxExpenseContinuingOperations"],
    "pretax_income": [
        "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
        "IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments",
        "ProfitLossBeforeTax",
    ],
}

# Units accepted per field. Money for everything except the share count.
_SHARE_FIELDS = {"diluted_shares"}


def annual_fact_series(session, cik: str, tag_names: list[str], *, shares: bool = False) -> dict[str, float]:
    """Return {end_date: value} for `tag_names`, one value per fiscal-year end.

    Only annual forms are considered. Where the same period end appears in several
    filings (the SEC repeats comparatives), the value from the *latest* filing wins
    — so a restated figure supersedes the original. `shares=True` selects share-unit
    facts (the diluted share count); otherwise monetary units are kept.
    """
    stmt = select(CompanyFact).where(
        CompanyFact.cik == cik,
        CompanyFact.tag.in_(tag_names),
        CompanyFact.form.in_(ANNUAL_FORMS),
    )
    rows = session.execute(stmt).scalars().all()

    allowed_units = {"shares"} if shares else CURRENCY_UNITS

    # (end_date -> (filed, value)); keep the latest-filed observation per period.
    best: dict[str, tuple[str, float]] = {}
    for row in rows:
        if row.unit not in allowed_units:
            continue
        if not row.end_date:
            continue
        filed = row.filed or ""
        existing = best.get(row.end_date)
        if existing is None or filed >= existing[0]:
            best[row.end_date] = (filed, row.value)

    return {end_date: value for end_date, (_, value) in best.items()}


def annual_fundamentals(cik: str, max_years: int = 4) -> list[dict]:
    """Build up to `max_years` annual snapshots for a company, newest first.

    Each snapshot is a dict of the FIELD_TAGS keys (plus `period_end`), holding
    that field's value at that fiscal-year end or None if the company never tagged
    it. Periods are the union of every field's fiscal-year ends, sorted descending,
    so `annual_fundamentals(cik)[0]` is the latest year and `[1]` the prior year —
    exactly the two inputs the year-over-year screen metrics consume.
    """
    normalized_cik = str(cik).zfill(10)

    with SessionLocal() as session:
        # Pull each field's per-period series once.
        field_series: dict[str, dict[str, float]] = {
            field: annual_fact_series(
                session, normalized_cik, tags, shares=(field in _SHARE_FIELDS)
            )
            for field, tags in FIELD_TAGS.items()
        }

    # The set of fiscal-year ends we have any data for, newest first.
    all_period_ends = sorted(
        {end for series in field_series.values() for end in series},
        reverse=True,
    )[:max_years]

    snapshots: list[dict] = []
    for period_end in all_period_ends:
        snapshot: dict = {"period_end": period_end}
        for field, series in field_series.items():
            snapshot[field] = series.get(period_end)
        snapshots.append(snapshot)

    return snapshots

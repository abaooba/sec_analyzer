"""Turn raw XBRL facts into a clean financial snapshot + display formatting.

Two responsibilities:
1. `compute_basic_snapshot` reads the most recent value of each key line item
   out of the company_facts table and derives a few ratios (margins, ROE proxy,
   free cash flow proxy, net assets). This is the numeric input to the
   financial-quality scorer.
2. `format_snapshot` / `format_large_number` make those numbers human-readable
   ("383.29B", "26.31%") for the CLI report.
"""

from sqlalchemy import select

from .db import SessionLocal
from .models import CompanyFact

# Annual vs interim filing forms; we accept facts from any of them.
ANNUAL_FORMS = {"10-K", "20-F", "40-F"}
INTERIM_FORMS = {"10-Q", "6-K"}
ALL_FINANCIAL_FORMS = list(ANNUAL_FORMS | INTERIM_FORMS)

# Units we treat as "money" when picking the latest monetary fact. Foreign
# filers report in their home currency, so we accept the major ones.
CURRENCY_UNITS = {"USD", "EUR", "JPY", "GBP", "CHF", "CNY", "TWD", "KRW", "CAD", "AUD"}


def format_large_number(value):
    """Human-friendly money formatting: billions -> 'B', millions -> 'M'."""
    if value is None:
        return None

    if abs(value) >= 1_000_000_000:
        return f"{value / 1_000_000_000:.2f}B"
    elif abs(value) >= 1_000_000:
        return f"{value / 1_000_000:.2f}M"
    else:
        return f"{value:.2f}"


def format_snapshot(snapshot: dict) -> dict:
    """Format a whole snapshot dict for display: ratios as %, money as B/M."""
    formatted: dict[str, str | None] = {}

    ratio_keys = {"operating_margin", "roe_proxy"}  # these are fractions -> show as %

    for key, value in snapshot.items():
        if value is None:
            formatted[key] = None
        elif key in ratio_keys:
            formatted[key] = f"{value:.2%}"
        else:
            formatted[key] = format_large_number(value)

    return formatted


def latest_fact(cik: str, tag_names: list[str], forms: list[str] | None = None):
    """Return the single most recent CompanyFact matching any of `tag_names`.

    `tag_names` is a synonym list (us-gaap + ifrs spellings of one concept).
    We prefer monetary/share facts, then sort by (filed date, period end date)
    descending and take the newest — this is how "latest revenue" is resolved.
    """
    with SessionLocal() as session:
        stmt = select(CompanyFact).where(
            CompanyFact.cik == cik,
            CompanyFact.tag.in_(tag_names),
        )

        if forms:
            stmt = stmt.where(CompanyFact.form.in_(forms))

        rows = session.execute(stmt).scalars().all()

        if not rows:
            return None

        # Keep monetary facts in any major currency, and share counts in shares
        # (drops oddball units like "pure" ratios that would distort things).
        filtered = [
            row for row in rows
            if row.unit in CURRENCY_UNITS or row.unit == "shares"
        ]

        if not filtered:
            filtered = list(rows)  # fall back to everything if the filter emptied it

        # Newest first: most recently filed, then latest period covered.
        filtered.sort(
            key=lambda x: (
                x.filed or "",
                x.end_date or "",
            ),
            reverse=True,
        )
        return filtered[0]


def compute_basic_snapshot(cik: str) -> dict:
    """Build the core financial snapshot dict used by the financial scorer.

    Pulls the latest value of each line item (trying us-gaap and ifrs synonyms),
    then derives ratios. Any missing input yields None for the derived value so
    downstream scoring can gracefully say "unavailable" rather than crash.
    """
    revenue = latest_fact(
        cik,
        [
            "Revenues",
            "RevenueFromContractWithCustomerExcludingAssessedTax",
            "Revenue",
            "RevenueFromContractsWithCustomers",
        ],
        ALL_FINANCIAL_FORMS,
    )
    net_income = latest_fact(cik, ["NetIncomeLoss", "ProfitLoss"], ALL_FINANCIAL_FORMS)
    assets = latest_fact(cik, ["Assets"], ALL_FINANCIAL_FORMS)
    liabilities = latest_fact(cik, ["Liabilities"], ALL_FINANCIAL_FORMS)
    equity = latest_fact(
        cik,
        ["StockholdersEquity", "Equity", "EquityAttributableToOwnersOfParent"],
        ALL_FINANCIAL_FORMS,
    )
    operating_cash_flow = latest_fact(
        cik,
        [
            "NetCashProvidedByUsedInOperatingActivities",
            "CashFlowsFromUsedInOperatingActivities",
            "NetCashFlowsFromUsedInOperatingActivities",
        ],
        ALL_FINANCIAL_FORMS,
    )
    capex = latest_fact(
        cik,
        [
            "PaymentsToAcquirePropertyPlantAndEquipment",
            "PaymentsToAcquireProductiveAssets",
            "PurchaseOfPropertyPlantAndEquipment",
            "PropertyPlantAndEquipmentAdditions",
        ],
        ALL_FINANCIAL_FORMS,
    )
    operating_income = latest_fact(
        cik,
        ["OperatingIncomeLoss", "OperatingProfitLoss"],
        ALL_FINANCIAL_FORMS,
    )
    long_term_debt = latest_fact(
        cik,
        ["LongTermDebtNoncurrent", "BorrowingsNoncurrent", "NoncurrentBorrowings"],
        ALL_FINANCIAL_FORMS,
    )
    diluted_shares = latest_fact(
        cik,
        [
            "WeightedAverageNumberOfDilutedSharesOutstanding",
            "WeightedAverageNumberOfSharesOutstandingDiluted",
            "WeightedAverageNumberOfOrdinarySharesOutstandingDiluted",
        ],
        ALL_FINANCIAL_FORMS,
    )

    result = {
        "revenue": revenue.value if revenue else None,
        "net_income": net_income.value if net_income else None,
        "assets": assets.value if assets else None,
        "liabilities": liabilities.value if liabilities else None,
        "equity": equity.value if equity else None,
        "operating_cash_flow": operating_cash_flow.value if operating_cash_flow else None,
        "capex": capex.value if capex else None,
        "operating_income": operating_income.value if operating_income else None,
        "long_term_debt": long_term_debt.value if long_term_debt else None,
        "diluted_shares": diluted_shares.value if diluted_shares else None,
    }

    # --- Derived ratios (each guarded against missing data / divide-by-zero) ---

    # Operating margin = operating income / revenue (profitability of core ops).
    if result["revenue"] is not None and result["operating_income"] is not None and result["revenue"] != 0:
        result["operating_margin"] = result["operating_income"] / result["revenue"]
    else:
        result["operating_margin"] = None

    # ROE proxy = net income / equity (how efficiently equity generates profit).
    if result["equity"] is not None and result["net_income"] is not None and result["equity"] != 0:
        result["roe_proxy"] = result["net_income"] / result["equity"]
    else:
        result["roe_proxy"] = None

    # Free cash flow proxy = operating cash flow minus capex (cash after
    # reinvestment). abs(capex) because the sign convention varies by filer.
    if result["operating_cash_flow"] is not None and result["capex"] is not None:
        result["free_cash_flow_proxy"] = result["operating_cash_flow"] - abs(result["capex"])
    else:
        result["free_cash_flow_proxy"] = None

    # Net assets = assets - liabilities (book value / shareholder cushion).
    if result["assets"] is not None and result["liabilities"] is not None:
        result["net_assets"] = result["assets"] - result["liabilities"]
    else:
        result["net_assets"] = None

    return result

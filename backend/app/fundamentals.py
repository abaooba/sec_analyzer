from sqlalchemy import select

from .db import SessionLocal
from .models import CompanyFact
from .sec_client import SECClient

TARGET_TAGS = {
    "us-gaap": {
        "Revenues",
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "NetIncomeLoss",
        "Assets",
        "Liabilities",
        "StockholdersEquity",
        "NetCashProvidedByUsedInOperatingActivities",
        "PaymentsToAcquirePropertyPlantAndEquipment",
        "LongTermDebtNoncurrent",
        "InterestExpenseAndOther",
        "GrossProfit",
        "OperatingIncomeLoss",
        "WeightedAverageNumberOfDilutedSharesOutstanding",
    },
    "ifrs-full": {
        "Revenue",
        "RevenueFromContractsWithCustomers",
        "ProfitLoss",
        "Assets",
        "Liabilities",
        "Equity",
        "EquityAttributableToOwnersOfParent",
        "CashFlowsFromUsedInOperatingActivities",
        "NetCashFlowsFromUsedInOperatingActivities",
        "PurchaseOfPropertyPlantAndEquipment",
        "PropertyPlantAndEquipmentAdditions",
        "BorrowingsNoncurrent",
        "NoncurrentBorrowings",
        "OperatingProfitLoss",
        "WeightedAverageNumberOfSharesOutstandingDiluted",
        "WeightedAverageNumberOfOrdinarySharesOutstandingDiluted",
    },
}


def ingest_company_facts(cik: str):
    client = SECClient()
    facts = client.get_company_facts(cik)

    company_cik = str(facts["cik"]).zfill(10)
    all_taxonomies = facts.get("facts", {})

    print(f"Ingesting company facts for CIK: {company_cik}")

    inserted_count = 0
    skipped_count = 0

    with SessionLocal() as session:
        for taxonomy, taxonomy_facts in all_taxonomies.items():
            if taxonomy not in TARGET_TAGS:
                continue

            for tag, payload in taxonomy_facts.items():
                if tag not in TARGET_TAGS[taxonomy]:
                    continue

                print(f"\nProcessing taxonomy/tag: {taxonomy}:{tag}")

                units = payload.get("units", {})
                for unit, observations in units.items():
                    print(f"  Unit: {unit} | Observations: {len(observations)}")

                    for obs in observations:
                        if "val" not in obs:
                            skipped_count += 1
                            continue

                        fiscal_year = int(obs.get("fy", 0) or 0)
                        fiscal_period = str(obs.get("fp", ""))
                        form = str(obs.get("form", ""))
                        filed = str(obs.get("filed", ""))
                        end_date = str(obs.get("end", ""))

                        stmt = select(CompanyFact).where(
                            CompanyFact.cik == company_cik,
                            CompanyFact.taxonomy == taxonomy,
                            CompanyFact.tag == tag,
                            CompanyFact.unit == unit,
                            CompanyFact.fiscal_year == fiscal_year,
                            CompanyFact.fiscal_period == fiscal_period,
                            CompanyFact.form == form,
                            CompanyFact.filed == filed,
                            CompanyFact.end_date == end_date,
                        )
                        existing_fact = session.execute(stmt).scalar_one_or_none()

                        if existing_fact is not None:
                            skipped_count += 1
                            continue

                        try:
                            value = float(obs["val"])
                        except (TypeError, ValueError):
                            skipped_count += 1
                            continue

                        fact = CompanyFact(
                            cik=company_cik,
                            taxonomy=taxonomy,
                            tag=tag,
                            unit=unit,
                            fiscal_year=fiscal_year,
                            fiscal_period=fiscal_period,
                            form=form,
                            filed=filed,
                            end_date=end_date,
                            value=value,
                        )
                        session.add(fact)
                        inserted_count += 1

        session.commit()

    print("\nCompany facts ingestion complete.")
    print(f"Inserted facts: {inserted_count}")
    print(f"Skipped facts: {skipped_count}")

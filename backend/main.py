import json
import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.app.db import init_db
from backend.app.ingest import ingest_company, delete_local_filings_for_company
from backend.app.fundamentals import ingest_company_facts
from backend.app.opinion import build_full_opinion

# #JSON OUTPUT
# def main():
#     cik = input("Enter company CIK: ").strip()
#     company_name = input("Enter company name: ").strip()
#     ticker = input("Enter ticker: ").strip().upper()

#     normalized_cik = cik.zfill(10)

#     init_db()

#     try:
#         ingest_company(normalized_cik)
#         ingest_company_facts(normalized_cik)

#         result = build_full_opinion(normalized_cik, company_name, ticker)

#         print(json.dumps(result, indent=2))

#     finally:
#         delete_local_filings_for_company(normalized_cik)


# if __name__ == "__main__":
#     main()


#NORMAL OUTPUT FOR TESTING N SHI
import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.app.company_lookup import find_company_match
from backend.app.db import init_db
from backend.app.ingest import ingest_company, delete_local_filings_for_company
from backend.app.fundamentals import ingest_company_facts
from backend.app.metrics import format_snapshot
from backend.app.opinion import build_full_opinion


def print_section_title(title: str):
    print(f"\n{title}")
    print("-" * len(title))


def print_score(label: str, value):
    print(f"{label}: {value}")


def print_list_section(title: str, items: list[str]):
    print_section_title(title)
    if not items:
        print("None")
        return

    for item in items:
        print(f"- {item}")


def print_dict_section(title: str, data: dict):
    print_section_title(title)
    for key, value in data.items():
        label = key.replace("_", " ").title()
        print(f"{label}: {value}")


def main():
    company_input = input("Enter company name: ").strip()

    if not company_input:
        print("No company name entered.")
        return

    init_db()

    match = find_company_match(company_input)

    if not match:
        print(f'Could not find a company match for "{company_input}".')
        return

    normalized_cik = match["cik"]
    company_name = match["company_name"]
    ticker = match["ticker"]

    print("\nMatched company:")
    print(f"Name: {company_name}")
    print(f"Ticker: {ticker}")
    print(f"CIK: {normalized_cik}")

    try:
        ingest_company(normalized_cik)
        ingest_company_facts(normalized_cik)

        result = build_full_opinion(normalized_cik, company_name, ticker)

        financial_metrics = result["details"]["financial"].get("metrics_used", {})
        formatted_financials = format_snapshot(financial_metrics)

        print("\n" + "=" * 60)
        print(f"SEC ANALYZER REPORT: {company_name} ({ticker})")
        print("=" * 60)

        print_section_title("Overview")
        print(f"Company Name: {result['company_name']}")
        print(f"Ticker: {result['ticker']}")
        print(f"CIK: {result['company_cik']}")
        print(f"Overall Score: {result['overall_score']}")

        print_section_title("Score Breakdown")
        scores = result.get("scores", {})
        for key, value in scores.items():
            label = key.replace("_", " ").title()
            print_score(label, value)

        print_section_title("Summary")
        print(result.get("summary", "No summary available."))

        print_list_section("Strengths", result.get("strengths", []))
        print_list_section("Weaknesses", result.get("weaknesses", []))
        print_list_section("Recent Changes", result.get("recent_changes", []))

        print_dict_section("Financial Snapshot", formatted_financials)

        llm = result.get("llm_analysis")
        if llm:
            print("\n" + "=" * 60)
            print("AI ANALYSIS (Claude Opus 4.7)")
            print("=" * 60)

            print_section_title("Investment Thesis")
            print(llm.get("investment_thesis", ""))

            print_section_title("Enhanced Summary")
            print(llm.get("enhanced_summary", ""))

            print_list_section("Key Risks", llm.get("key_risks", []))
            print_list_section("Key Strengths", llm.get("key_strengths", []))

            red_flags = llm.get("red_flags", [])
            if red_flags:
                print_list_section("Red Flags", red_flags)

            print_section_title("Score Commentary")
            print(llm.get("score_commentary", ""))

    finally:
        delete_local_filings_for_company(normalized_cik)


if __name__ == "__main__":
    main()
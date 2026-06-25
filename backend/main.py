"""CLI entry point — the interactive, human-readable version of the analyzer.

Run with: `python -m backend.main` (or `python backend/main.py`).
Prompts for a company name, runs the same pipeline as the API, and pretty-prints
a formatted report to the terminal (scores, summary, strengths/weaknesses, the
financial snapshot, and the AI analysis).

The commented-out block below is an earlier variant that took CIK/ticker
directly and dumped raw JSON — kept as a reference. The active `main()` further
down is the name-driven, formatted version.

The sys.path shim makes this runnable both as a module (`-m backend.main`) and
as a loose script: if there's no package context, it adds the repo root to the
import path so `from backend.app...` resolves.
"""

import json
import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.app.db import init_db
from backend.app.ingest import ingest_company, delete_local_filings_for_company
from backend.app.fundamentals import ingest_company_facts
from backend.app.opinion import build_full_opinion

# #JSON OUTPUT  (legacy CIK/ticker-driven variant, kept for reference)
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


# --- ACTIVE: name-driven, formatted terminal report ---
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
from backend.app.llm_analysis import LLM_DISPLAY_NAME


# --- Small print helpers for consistent report formatting ---
def print_section_title(title: str):
    """Print a title with a dashed underline the same width."""
    print(f"\n{title}")
    print("-" * len(title))


def print_score(label: str, value):
    print(f"{label}: {value}")


def print_list_section(title: str, items: list[str]):
    """Print a titled bullet list, or 'None' if empty."""
    print_section_title(title)
    if not items:
        print("None")
        return

    for item in items:
        print(f"- {item}")


def print_dict_section(title: str, data: dict):
    """Print a dict as 'Title Cased Key: value' lines."""
    print_section_title(title)
    for key, value in data.items():
        label = key.replace("_", " ").title()
        print(f"{label}: {value}")


def main():
    # 1. Ask the user for a company and resolve it to a CIK.
    company_input = input("Enter company name: ").strip()

    if not company_input:
        print("No company name entered.")
        return

    init_db()  # make sure DB tables exist

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
        # 2. Ingest filings + financial facts, then 3. build the full opinion.
        ingest_company(normalized_cik)
        ingest_company_facts(normalized_cik)

        result = build_full_opinion(normalized_cik, company_name, ticker)

        # Pull the raw metrics back out and format them for display.
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

        # The AI section only prints if the LLM step actually produced output.
        llm = result.get("llm_analysis")
        if llm:
            print("\n" + "=" * 60)
            print(f"AI ANALYSIS ({LLM_DISPLAY_NAME})")
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
        # Clean up cached HTML regardless of success/failure.
        delete_local_filings_for_company(normalized_cik)


if __name__ == "__main__":
    main()
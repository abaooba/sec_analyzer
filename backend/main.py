from frontend.app.db import init_db
from frontend.app.ingest import ingest_company
from frontend.app.fundamentals import ingest_company_facts
from frontend.app.opinion import build_full_opinion
from frontend.app.company_lookup import find_company_match


def main():
    company_name = input("Enter company name: ").strip()
    ticker = input("Enter ticker (optional): ").strip() or None

    try:
        print("\nLooking up company...")
        match = find_company_match(company_name=company_name, ticker=ticker)

        if match is None:
            print("Could not find a matching company.")
            return

        normalized_cik = match["cik"]
        resolved_name = match["company_name"]
        resolved_ticker = match["ticker"]

        print(f"Matched company: {resolved_name}")
        print(f"Ticker: {resolved_ticker}")
        print(f"CIK: {normalized_cik}")

        print("\nInitializing database...")
        init_db()

        print("Ingesting company filings...")
        ingest_company(normalized_cik)

        print("Ingesting company facts...")
        ingest_company_facts(normalized_cik)

        print("Building full opinion...")
        result = build_full_opinion(
            cik=normalized_cik,
            company_name=resolved_name,
            ticker=resolved_ticker,
        )

        print("\nOVERALL SCORE:", result["overall_score"])

        print("\nSUB-SCORES:")
        for name, score in result["scores"].items():
            print(f"{name}: {score}")

        print("\nSTRENGTHS:")
        for item in result["strengths"]:
            print("-", item)

        print("\nWEAKNESSES:")
        for item in result["weaknesses"]:
            print("-", item)

        print("\nRECENT CHANGES:")
        for item in result["recent_changes"]:
            print("-", item)

        print("\nSUMMARY:")
        print(result["summary"])

    except Exception as e:
        print("\nSomething went wrong:")
        print(e)


if __name__ == "__main__":
    main()
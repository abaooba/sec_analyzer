"""The orchestrator — ties every scorer together into one final opinion.

`build_full_opinion` is the brain of the app. It:
  1. extracts the latest filing's sections,
  2. runs all five scorers (financial, risk, business model, moat, geopolitics),
  3. runs year-over-year change detection,
  4. blends the five scores into a single weighted `overall_score`,
  5. derives human-readable strengths / weaknesses / summary with rule-based
     thresholds,
  6. and finally layers an LLM narrative on top (llm_analysis).

The helper functions above it are pure presentation logic: they translate raw
numbers into English bullet points. Note the scores are combined so that risk
and geopolitics are INVERTED (100 - score) because high values there are bad.
"""

import logging

from .change_detection import detect_filing_changes
from .llm_analysis import generate_llm_analysis
from .parse_filings import extract_latest_annual_sections, choose_section_text
from .scoring.business_model import score_business_model_text
from .scoring.financials import score_financial_quality
from .scoring.geopolitics import score_geopolitical_impact
from .scoring.moat import score_moat_text
from .scoring.risk import score_risk_text

logger = logging.getLogger(__name__)


def clamp_overall_score(score: float) -> float:
    """Round and constrain the blended score to [0, 100]."""
    return max(0, min(round(score, 2), 100))


def build_strengths(financial_result: dict, business_result: dict, moat_result: dict) -> list[str]:
    """Turn high category scores into up-to-5 plain-English strength bullets."""
    strengths = []

    if financial_result["total_financial_score"] >= 75:
        strengths.append("Strong overall financial quality.")

    if business_result["total_business_model_score"] >= 80:
        strengths.append("Strong and durable business model characteristics.")

    if moat_result["total_moat_score"] >= 75:
        strengths.append("Strong competitive positioning and moat signals.")

    if business_result["category_scores"].get("ecosystem_strength", 0) >= 10:
        strengths.append("Ecosystem strength appears to support customer retention and product integration.")

    if financial_result["category_scores"].get("cash_generation", 0) >= 15:
        strengths.append("Business generates strong cash flow.")

    return strengths[:5]


def build_weaknesses(
    financial_result: dict,
    risk_result: dict,
    business_result: dict,
    geopolitical_result: dict | None = None,
) -> list[str]:
    """Turn elevated-risk / weak-category signals into weakness bullets."""
    weaknesses = []

    if risk_result["total_risk_score"] >= 60:
        weaknesses.append("Risk disclosures appear elevated.")

    if business_result["category_scores"].get("operational_intensity", 0) >= 8:
        weaknesses.append("Operations appear complex and operationally intensive.")

    if business_result["category_scores"].get("customer_dependency", 0) >= 8:
        weaknesses.append("Some dependency on channels, partners, or third parties appears present.")

    if financial_result["category_scores"].get("leverage", 0) <= 10:
        weaknesses.append("Leverage profile is not especially strong.")

    if financial_result["category_scores"].get("balance_sheet_strength", 0) <= 10:
        weaknesses.append("Balance sheet strength appears only moderate.")

    if geopolitical_result and geopolitical_result["total_geopolitical_score"] >= 40:
        weaknesses.append("Current geopolitical conditions may materially pressure the outlook.")

    return weaknesses[:5]


def build_recent_changes(change_result: dict) -> list[str]:
    """Translate the YoY change-detection output into readable change bullets."""
    changes: list[str] = []

    # If change detection bailed (e.g. <2 annual filings), there's nothing to say.
    if not change_result or change_result.get("message"):
        return changes

    score_changes = change_result.get("score_changes", {})

    risk_change = score_changes.get("risk", {}).get("change", 0)
    business_change = score_changes.get("business_model", {}).get("change", 0)
    moat_change = score_changes.get("moat", {}).get("change", 0)

    if risk_change > 0:
        changes.append(f"Risk score increased by {risk_change}.")
    elif risk_change < 0:
        changes.append(f"Risk score decreased by {abs(risk_change)}.")

    if business_change > 0:
        changes.append(f"Business model score increased by {business_change}.")
    elif business_change < 0:
        changes.append(f"Business model score decreased by {abs(business_change)}.")

    if moat_change > 0:
        changes.append(f"Moat score increased by {moat_change}.")
    elif moat_change < 0:
        changes.append(f"Moat score decreased by {abs(moat_change)}.")

    new_risk_sentences = change_result.get("new_sentences", {}).get("risk_factors", [])
    if new_risk_sentences:
        changes.append("Latest filing contains new risk-factor language.")

    return changes[:5]


def write_summary(
    financial_result: dict,
    risk_result: dict,
    business_result: dict,
    moat_result: dict,
    strengths: list[str],
    weaknesses: list[str],
    recent_changes: list[str],
    geopolitical_result: dict | None = None,
) -> str:
    """Compose a paragraph summary by mapping score bands to canned phrases.

    Builds clauses like "financially strong" + "with a strong business model" +
    "and strong moat characteristics", then appends risk, geopolitical, and the
    single top strength/weakness/change. This is the deterministic summary; the
    LLM later produces a richer 'enhanced_summary' alongside it.
    """
    overall_financial = financial_result["total_financial_score"]
    overall_risk = risk_result["total_risk_score"]
    overall_business = business_result["total_business_model_score"]
    overall_moat = moat_result["total_moat_score"]

    parts = []

    if overall_financial >= 75:
        parts.append("The company appears financially strong")
    elif overall_financial >= 55:
        parts.append("The company appears financially solid but not exceptional")
    else:
        parts.append("The company appears financially weaker")

    if overall_business >= 80:
        parts.append("with a strong business model")
    elif overall_business >= 60:
        parts.append("with a decent business model")
    else:
        parts.append("with a less durable business model")

    if overall_moat >= 75:
        parts.append("and strong moat characteristics")
    elif overall_moat >= 55:
        parts.append("and some moat characteristics")
    else:
        parts.append("and limited moat signals")

    summary = " ".join(parts) + "."

    if overall_risk >= 70:
        summary += " Risk disclosures are elevated and should be watched closely."
    elif overall_risk >= 45:
        summary += " Risk appears meaningful but not extreme."
    else:
        summary += " Risk disclosures do not appear unusually severe."

    if geopolitical_result:
        geo_score = geopolitical_result["total_geopolitical_score"]
        if geo_score >= 55:
            summary += " Current geopolitical conditions appear significantly adverse."
        elif geo_score >= 30:
            summary += " Current geopolitical conditions create a moderate external overhang."
        else:
            summary += " Current geopolitical conditions do not appear unusually severe."

    if strengths:
        summary += f" Key strength: {strengths[0]}"
    if weaknesses:
        summary += f" Key weakness: {weaknesses[0]}"
    if recent_changes:
        summary += f" Recent change: {recent_changes[0]}"

    return summary


def build_full_opinion(
    cik: str,
    company_name: str,
    ticker: str | None = None,
    geo_terms: list[str] | None = None,
) -> dict:
    """Run the whole analysis pipeline and return the complete opinion dict.

    Assumes ingest_company + ingest_company_facts have already populated the DB
    for this CIK. Returns a big nested dict: top-level scores + strengths/
    weaknesses/summary for display, a `details` block with every scorer's full
    output, and `llm_analysis` with the AI narrative (or None if unavailable).
    """
    normalized_cik = str(cik).zfill(10)

    # Pull the best filing's text once and reuse for the text-based scorers.
    sections = extract_latest_annual_sections(normalized_cik)
    # Pick the best available text for risk scoring (risk_factors preferred).
    risk_text = choose_section_text(
        sections,
        "risk_factors",
        "mdna",
        "business",
        "full_text",
        min_chars=500,
    )
    business_text = choose_section_text(
        sections,
        "business",
        "mdna",
        "risk_factors",
        "full_text",
        min_chars=500,
    )

    # --- Run all five scorers (financials uses numbers, the rest use text) ---
    financial_result = score_financial_quality(normalized_cik)
    risk_result = score_risk_text(risk_text)
    business_result = score_business_model_text(business_text)
    moat_result = score_moat_text(business_text)
    change_result = detect_filing_changes(normalized_cik)  # YoY comparison
    geopolitical_result = score_geopolitical_impact(
        cik=normalized_cik,
        company_name=company_name,
        ticker=ticker,
        extra_terms=geo_terms
        or [
            "tariffs",
            "china",
            "supply chain",
            "regulation",
            "antitrust",
            "iran",
            "middle east",
            "strait of hormuz",
            "red sea",
            "oil prices",
            "shipping disruption",
        ],
    )

    # Weighted blend into one 0-100 number. Risk and geopolitics are INVERTED
    # (100 - score) so that "more risk" lowers the overall, not raises it.
    # Weights sum to 1.0: financial .25, risk .20, business .20, moat .15, geo .20.
    overall_score = (
        financial_result["total_financial_score"] * 0.25
        + (100 - risk_result["total_risk_score"]) * 0.20
        + business_result["total_business_model_score"] * 0.20
        + moat_result["total_moat_score"] * 0.15
        + (100 - geopolitical_result["total_geopolitical_score"]) * 0.20
    )
    overall_score = clamp_overall_score(overall_score)

    strengths = build_strengths(financial_result, business_result, moat_result)
    weaknesses = build_weaknesses(financial_result, risk_result, business_result, geopolitical_result)
    recent_changes = build_recent_changes(change_result)

    summary = write_summary(
        financial_result,
        risk_result,
        business_result,
        moat_result,
        strengths,
        weaknesses,
        recent_changes,
        geopolitical_result,
    )

    # Assemble the response: flat fields for display + a `details` block holding
    # each scorer's full output (used by the API consumer and the LLM step).
    opinion = {
        "company_cik": normalized_cik,
        "company_name": company_name,
        "ticker": ticker,
        "overall_score": overall_score,
        "scores": {
            "financial": financial_result["total_financial_score"],
            "risk": risk_result["total_risk_score"],
            "business_model": business_result["total_business_model_score"],
            "moat": moat_result["total_moat_score"],
            "geopolitical": geopolitical_result["total_geopolitical_score"],
        },
        "strengths": strengths,
        "weaknesses": weaknesses,
        "recent_changes": recent_changes,
        "summary": summary,
        "details": {
            "financial": financial_result,
            "risk": risk_result,
            "business_model": business_result,
            "moat": moat_result,
            "geopolitical": geopolitical_result,
            "change_detection": change_result,
        },
        "llm_analysis": None,  # filled in below if the LLM is configured
    }

    # Final layer: ask the LLM to write a richer narrative from everything above.
    # Returns None (and we keep the rule-based opinion as-is) if no API key/error.
    logger.info("Generating AI analysis...")
    llm_result = generate_llm_analysis(company_name, ticker, opinion, sections)
    if llm_result:
        opinion["llm_analysis"] = llm_result.model_dump()  # pydantic -> dict

    return opinion

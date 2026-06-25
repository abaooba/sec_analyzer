"""Year-over-year change detection between a company's two latest annual filings.

Compares this year's 10-K/20-F against last year's to answer "what changed?":
  - section length deltas (did Risk Factors grow a lot?)
  - score deltas (did the risk/business/moat scores move?)
  - brand-new sentences that appeared this year (set difference of sentences)
These feed the "Recent Changes" section of the opinion. Needs >=2 annual
filings on hand or it returns a polite "not enough filings" message.
"""

from sqlalchemy import select

from .db import SessionLocal
from .models import Filing
from .parse_filings import (
    load_filing_html,
    filing_html_to_text,
    extract_key_sections,
    choose_section_text,
)
from .scoring.business_model import score_business_model_text
from .scoring.moat import score_moat_text
from .scoring.risk import score_risk_text


ANNUAL_FORMS = ("10-K", "20-F", "40-F")


def get_latest_annual_filings(cik: str, limit: int = 4) -> list[Filing]:
    """Return up to `limit` most-recent annual filings (newest first)."""
    normalized_cik = str(cik).zfill(10)

    with SessionLocal() as session:
        stmt = (
            select(Filing)
            .where(Filing.cik == normalized_cik, Filing.form.in_(ANNUAL_FORMS))
            .order_by(Filing.filing_date.desc())
            .limit(limit)
        )
        return list(session.execute(stmt).scalars().all())


def get_latest_two_annual_filings(cik: str):
    """Return (newest, second-newest) annual filings, or (None, None) if <2 exist."""
    filings = get_latest_annual_filings(cik, limit=2)
    if len(filings) < 2:
        return None, None
    return filings[0], filings[1]


def extract_sections_from_filing(filing: Filing) -> dict:
    html = load_filing_html(filing.local_path)
    text = filing_html_to_text(html)
    sections = extract_key_sections(text)

    return {
        "filing_date": filing.filing_date,
        "filing_path": filing.local_path,
        "form": filing.form,
        "business": sections.get("business", ""),
        "risk_factors": sections.get("risk_factors", ""),
        "mdna": sections.get("mdna", ""),
        "full_text": sections.get("full_text", ""),
    }


def split_into_sentences(text: str) -> list[str]:
    """Same naive sentence splitter as the scorers (split after . ! ?)."""
    if not text:
        return []

    import re
    text = re.sub(r"\s+", " ", text).strip()
    sentences = re.split(r"(?<=[.!?])\s+", text)

    return [sentence.strip() for sentence in sentences if sentence.strip()]


def get_new_sentences(current_text: str, previous_text: str, max_sentences: int = 10) -> list[str]:
    """Sentences present this year but NOT last year (a simple set difference).

    Surfaces newly-added language — often the most analytically interesting part
    of a filing (e.g. a brand-new risk the company just started disclosing).
    """
    current_sentences = split_into_sentences(current_text)
    previous_sentences = set(split_into_sentences(previous_text))  # set for O(1) lookup

    new_sentences = []
    for sentence in current_sentences:
        if sentence not in previous_sentences:
            new_sentences.append(sentence)

        if len(new_sentences) >= max_sentences:
            break

    return new_sentences


def compare_section_lengths(current_sections: dict, previous_sections: dict) -> dict:
    """Character-count delta per section between the two filings."""
    results = {}

    for section_name in ["business", "risk_factors", "mdna"]:
        current_text = current_sections.get(section_name) or ""
        previous_text = previous_sections.get(section_name) or ""

        current_length = len(current_text)
        previous_length = len(previous_text)
        length_change = current_length - previous_length

        results[section_name] = {
            "current_length": current_length,
            "previous_length": previous_length,
            "length_change": length_change,
        }

    return results


def compare_scores(current_sections: dict, previous_sections: dict) -> dict:
    """Re-run risk/business/moat scoring on both years and report the deltas."""
    current_risk_text = choose_section_text(
        current_sections,
        "risk_factors",
        "mdna",
        "business",
        "full_text",
        min_chars=500,
    )
    previous_risk_text = choose_section_text(
        previous_sections,
        "risk_factors",
        "mdna",
        "business",
        "full_text",
        min_chars=500,
    )

    current_business_text = choose_section_text(
        current_sections,
        "business",
        "mdna",
        "risk_factors",
        "full_text",
        min_chars=500,
    )
    previous_business_text = choose_section_text(
        previous_sections,
        "business",
        "mdna",
        "risk_factors",
        "full_text",
        min_chars=500,
    )

    current_risk = score_risk_text(current_risk_text)
    previous_risk = score_risk_text(previous_risk_text)

    current_business_model = score_business_model_text(current_business_text)
    previous_business_model = score_business_model_text(previous_business_text)

    current_moat = score_moat_text(current_business_text)
    previous_moat = score_moat_text(previous_business_text)

    return {
        "risk": {
            "current": current_risk["total_risk_score"],
            "previous": previous_risk["total_risk_score"],
            "change": round(current_risk["total_risk_score"] - previous_risk["total_risk_score"], 2),
        },
        "business_model": {
            "current": current_business_model["total_business_model_score"],
            "previous": previous_business_model["total_business_model_score"],
            "change": round(
                current_business_model["total_business_model_score"]
                - previous_business_model["total_business_model_score"],
                2,
            ),
        },
        "moat": {
            "current": current_moat["total_moat_score"],
            "previous": previous_moat["total_moat_score"],
            "change": round(current_moat["total_moat_score"] - previous_moat["total_moat_score"], 2),
        },
    }


def detect_filing_changes(cik: str) -> dict:
    """Top-level: full YoY comparison (lengths, score deltas, new sentences)."""
    current_filing, previous_filing = get_latest_two_annual_filings(cik)

    if current_filing is None or previous_filing is None:
        return {
            "current_filing_date": None,
            "previous_filing_date": None,
            "message": "Not enough annual filings found to compare.",
        }

    current_sections = extract_sections_from_filing(current_filing)
    previous_sections = extract_sections_from_filing(previous_filing)

    section_lengths = compare_section_lengths(current_sections, previous_sections)
    score_changes = compare_scores(current_sections, previous_sections)

    current_business_text = choose_section_text(
        current_sections,
        "business",
        "mdna",
        "risk_factors",
        "full_text",
        min_chars=500,
    )
    previous_business_text = choose_section_text(
        previous_sections,
        "business",
        "mdna",
        "risk_factors",
        "full_text",
        min_chars=500,
    )
    current_risk_text = choose_section_text(
        current_sections,
        "risk_factors",
        "mdna",
        "business",
        "full_text",
        min_chars=500,
    )
    previous_risk_text = choose_section_text(
        previous_sections,
        "risk_factors",
        "mdna",
        "business",
        "full_text",
        min_chars=500,
    )
    current_mdna_text = choose_section_text(
        current_sections,
        "mdna",
        "business",
        "risk_factors",
        "full_text",
        min_chars=500,
    )
    previous_mdna_text = choose_section_text(
        previous_sections,
        "mdna",
        "business",
        "risk_factors",
        "full_text",
        min_chars=500,
    )

    new_business_sentences = get_new_sentences(
        current_business_text,
        previous_business_text,
    )
    new_risk_sentences = get_new_sentences(
        current_risk_text,
        previous_risk_text,
    )
    new_mdna_sentences = get_new_sentences(
        current_mdna_text,
        previous_mdna_text,
    )

    return {
        "current_filing_date": current_sections["filing_date"],
        "previous_filing_date": previous_sections["filing_date"],
        "current_filing_path": current_sections["filing_path"],
        "previous_filing_path": previous_sections["filing_path"],
        "section_lengths": section_lengths,
        "score_changes": score_changes,
        "new_sentences": {
            "business": new_business_sentences,
            "risk_factors": new_risk_sentences,
            "mdna": new_mdna_sentences,
        },
    }


def _trajectory_trends(points: list[dict]) -> dict:
    """Latest move per dimension (newest point minus the one before it)."""
    if len(points) < 2:
        return {}
    latest, prior = points[-1], points[-2]
    trends = {}
    for dimension in ("risk", "business_model", "moat"):
        delta = round(latest[dimension] - prior[dimension], 2)
        direction = "up" if delta > 0 else "down" if delta < 0 else "flat"
        trends[dimension] = {"change": delta, "direction": direction}
    return trends


def build_score_trajectory(cik: str, limit: int = 4) -> dict:
    """Risk / business-model / moat text scores across the last `limit` annual
    filings (oldest -> newest), so the disclosure profile's trend is visible.

    Only the text-based scores get a trajectory: financials come from point-in-time
    XBRL facts and geopolitics from live news, so neither has a per-filing history.
    Filings whose cached HTML can't be loaded are skipped (best-effort).
    """
    filings = get_latest_annual_filings(cik, limit=limit)

    points = []
    for filing in reversed(filings):  # oldest -> newest
        try:
            sections = extract_sections_from_filing(filing)
        except Exception:
            continue  # cached HTML missing/unreadable -> skip this year

        risk_text = choose_section_text(
            sections, "risk_factors", "mdna", "business", "full_text", min_chars=500
        )
        business_text = choose_section_text(
            sections, "business", "mdna", "risk_factors", "full_text", min_chars=500
        )
        points.append(
            {
                "filing_date": filing.filing_date,
                "form": filing.form,
                "risk": score_risk_text(risk_text)["total_risk_score"],
                "business_model": score_business_model_text(business_text)[
                    "total_business_model_score"
                ],
                "moat": score_moat_text(business_text)["total_moat_score"],
            }
        )

    return {
        "points": points,
        "filings_compared": len(points),
        "trends": _trajectory_trends(points),
    }

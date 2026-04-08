from sqlalchemy import select

from frontend.app.db import SessionLocal
from frontend.app.models import Filing
from frontend.app.parse_filings import (
    load_filing_html,
    filing_html_to_text,
    extract_key_sections,
    choose_section_text,
)
from frontend.app.scoring.risk import score_risk_text
from frontend.app.scoring.business_model import score_business_model_text
from frontend.app.scoring.moat import score_moat_text


ANNUAL_FORMS = ("10-K", "20-F", "40-F")


def get_latest_two_annual_filings(cik: str):
    normalized_cik = str(cik).zfill(10)

    with SessionLocal() as session:
        stmt = (
            select(Filing)
            .where(Filing.cik == normalized_cik, Filing.form.in_(ANNUAL_FORMS))
            .order_by(Filing.filing_date.desc())
        )
        filings = session.execute(stmt).scalars().all()

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
    if not text:
        return []

    import re
    text = re.sub(r"\s+", " ", text).strip()
    sentences = re.split(r"(?<=[.!?])\s+", text)

    return [sentence.strip() for sentence in sentences if sentence.strip()]


def get_new_sentences(current_text: str, previous_text: str, max_sentences: int = 10) -> list[str]:
    current_sentences = split_into_sentences(current_text)
    previous_sentences = set(split_into_sentences(previous_text))

    new_sentences = []
    for sentence in current_sentences:
        if sentence not in previous_sentences:
            new_sentences.append(sentence)

        if len(new_sentences) >= max_sentences:
            break

    return new_sentences


def compare_section_lengths(current_sections: dict, previous_sections: dict) -> dict:
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

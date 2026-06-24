"""Tests for filing HTML -> text conversion and regex section extraction.

Uses a saved synthetic 10-K fixture (``fixtures/sample_10k.html``) with a table
of contents plus substantive Business / Risk Factors / MD&A sections, each tagged
with a unique marker so we can assert the extractor carves them apart cleanly
(and skips the TOC).
"""

from backend.app.parse_filings import (
    _looks_like_table_of_contents,
    choose_section_text,
    combine_section_texts,
    extract_key_sections,
    extract_latest_filing_sections,
    filing_html_to_text,
)
from backend.app.models import Filing


def make_filing(cik, form, filing_date, local_path, accession_no):
    return Filing(
        cik=cik,
        accession_no=accession_no,
        form=form,
        filing_date=filing_date,
        primary_doc="primary.htm",
        filing_url="https://example.test/filing",
        local_path=local_path,
    )


# --- HTML -> text ----------------------------------------------------------

def test_filing_html_to_text_strips_noise_and_tags(sample_10k_html):
    text = filing_html_to_text(sample_10k_html)
    assert "this script text must not appear" not in text  # <script> dropped
    assert "color: red" not in text                        # <style> dropped
    assert "<p>" not in text and "<html>" not in text      # tags stripped
    assert "BUSINESSMARKER" in text                        # content preserved


def test_filing_html_to_text_empty():
    assert filing_html_to_text("") == ""


# --- section extraction ----------------------------------------------------

def test_extract_key_sections_separates_business_risk_mdna(sample_10k_html):
    text = filing_html_to_text(sample_10k_html)
    sections = extract_key_sections(text)

    assert "BUSINESSMARKER" in sections["business"]
    assert "RISKMARKER" not in sections["business"]
    assert "MDNAMARKER" not in sections["business"]

    assert "RISKMARKER" in sections["risk_factors"]
    assert "BUSINESSMARKER" not in sections["risk_factors"]
    assert "MDNAMARKER" not in sections["risk_factors"]

    assert "MDNAMARKER" in sections["mdna"]
    assert "RISKMARKER" not in sections["mdna"]

    # full_text is the catch-all fallback and keeps everything.
    for marker in ("BUSINESSMARKER", "RISKMARKER", "MDNAMARKER"):
        assert marker in sections["full_text"]


def test_looks_like_table_of_contents():
    toc = "Item 1. Business 3 Item 1A. Risk Factors 8 Item 2. Properties 16 Item 7 MD&A 20"
    assert _looks_like_table_of_contents(toc) is True
    prose = "The company designs and sells products and invests in research and development."
    assert _looks_like_table_of_contents(prose) is False


# --- choose / combine helpers ---------------------------------------------

def test_choose_section_text_priority_and_min_chars():
    sections = {
        "risk_factors": "short",
        "mdna": "m" * 600,
        "business": "b" * 600,
        "full_text": "f" * 10,
    }
    # risk_factors is too short -> fall through to the first qualifying section.
    chosen = choose_section_text(
        sections, "risk_factors", "mdna", "business", "full_text", min_chars=500
    )
    assert chosen == "m" * 600


def test_choose_section_text_full_text_always_qualifies():
    sections = {"full_text": "tiny"}
    assert choose_section_text(sections, "risk_factors", "full_text", min_chars=500) == "tiny"


def test_choose_section_text_remembers_short_fallback():
    sections = {"risk_factors": "short"}
    assert choose_section_text(sections, "risk_factors", min_chars=500) == "short"
    assert choose_section_text({}, "risk_factors", "full_text", min_chars=500) == ""


def test_combine_section_texts_dedupes():
    sections = {"business": "a" * 600, "mdna": "b" * 600, "risk_factors": "a" * 600}
    combined = combine_section_texts(
        sections, "business", "mdna", "risk_factors", min_chars=500
    )
    assert combined.count("a" * 600) == 1   # duplicate business/risk text collapsed
    assert "b" * 600 in combined


# --- DB-driven filing selection (integration) ------------------------------

def test_pick_best_filing_prefers_annual_over_interim(
    patch_parse_filings_db, sample_10k_html, tmp_path
):
    """Form preference (annual 10-K) must beat a newer interim 10-Q, and the
    chosen filing's HTML must flow through to extracted sections."""
    cik = "0000000042"
    filing_path = tmp_path / "sample_10k.html"
    filing_path.write_text(sample_10k_html, encoding="utf-8")

    with patch_parse_filings_db() as session:
        session.add_all(
            [
                # Newer 10-Q (interim) ...
                make_filing(cik, "10-Q", "2024-05-01", "", "0000000042-24-000002"),
                # ... vs older 10-K (annual) which should still win on form rank.
                make_filing(cik, "10-K", "2024-02-01", str(filing_path), "0000000042-24-000001"),
            ]
        )
        session.commit()

    result = extract_latest_filing_sections(cik)

    assert result["form"] == "10-K"
    assert "BUSINESSMARKER" in result["business"]
    assert "RISKMARKER" in result["risk_factors"]


def test_extract_latest_filing_sections_no_filings_returns_empty(patch_parse_filings_db):
    result = extract_latest_filing_sections("0000000000")
    assert result["form"] is None
    assert result["business"] == ""
    assert result["risk_factors"] == ""

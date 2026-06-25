"""Tests for the forensic red-flag scorer."""

from backend.app.scoring.forensic import (
    FORENSIC_KEYWORDS,
    FORENSIC_WEIGHTS,
    score_forensic_text,
)


def test_clean_text_has_no_flags():
    result = score_forensic_text("The company had a strong year with record revenue and margins.")
    assert result["flags"] == []
    assert result["total_forensic_score"] == 0


def test_going_concern_flag_fires_with_evidence():
    text = (
        "There is substantial doubt about our ability to continue as a going concern. "
        "Management is evaluating financing options."
    )
    result = score_forensic_text(text)
    assert "going_concern" in result["flags"]
    assert result["total_forensic_score"] > 0
    assert result["evidence_sentences"]["going_concern"]  # at least one sentence


def test_multiple_flags_detected():
    text = (
        "We identified a material weakness in our internal control over financial reporting. "
        "We will restate our previously issued financial statements. "
        "The SEC investigation is ongoing and we received a subpoena."
    )
    result = score_forensic_text(text)
    assert {"material_weakness", "restatement", "sec_investigation"} <= set(result["flags"])
    assert result["total_forensic_score"] > 0


def test_keywords_and_weights_align():
    assert set(FORENSIC_KEYWORDS) == set(FORENSIC_WEIGHTS)
    for patterns in FORENSIC_KEYWORDS.values():
        assert patterns


def test_score_is_capped_to_0_100():
    text = "going concern. restatement. material weakness. impairment charge. " * 50
    result = score_forensic_text(text)
    assert 0 <= result["total_forensic_score"] <= 100

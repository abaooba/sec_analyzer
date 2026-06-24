"""Tests for the orchestrator: the weighted blend + the rule-based presentation
helpers (strengths / weaknesses / summary / recent-changes).

The blend formula is exercised through the *real* ``build_full_opinion`` with the
five scorers, change-detection, and the LLM all monkeypatched to fixed values.
That keeps the test offline (no SEC / Groq / DB) while still verifying the actual
weighting, the risk/geopolitics inversion, and the clamp — not a re-implementation.
"""

import pytest

import backend.app.opinion as opinion_mod
from backend.app.opinion import (
    build_full_opinion,
    build_recent_changes,
    build_strengths,
    build_weaknesses,
    clamp_overall_score,
    write_summary,
)


def _patch_pipeline(monkeypatch, *, financial, risk, business, moat, geo, change=None, llm=None):
    """Replace every external call build_full_opinion makes with a fixed stub."""
    if change is None:
        change = {"message": "not enough annual filings"}

    empty_sections = {"business": "", "risk_factors": "", "mdna": "", "full_text": ""}
    monkeypatch.setattr(opinion_mod, "extract_latest_annual_sections", lambda cik: empty_sections)
    monkeypatch.setattr(opinion_mod, "choose_section_text", lambda *a, **k: "")
    monkeypatch.setattr(
        opinion_mod, "score_financial_quality",
        lambda cik: {"total_financial_score": financial, "category_scores": {}},
    )
    monkeypatch.setattr(
        opinion_mod, "score_risk_text",
        lambda text: {"total_risk_score": risk, "category_scores": {}, "evidence_sentences": {}},
    )
    monkeypatch.setattr(
        opinion_mod, "score_business_model_text",
        lambda text: {"total_business_model_score": business, "category_scores": {}},
    )
    monkeypatch.setattr(
        opinion_mod, "score_moat_text",
        lambda text: {"total_moat_score": moat, "category_scores": {}},
    )
    monkeypatch.setattr(opinion_mod, "detect_filing_changes", lambda cik: change)
    monkeypatch.setattr(
        opinion_mod, "score_geopolitical_impact",
        lambda **k: {"total_geopolitical_score": geo},
    )
    monkeypatch.setattr(opinion_mod, "generate_llm_analysis", lambda *a, **k: llm)


def test_blend_formula_exact_weights_and_inversion(monkeypatch):
    _patch_pipeline(monkeypatch, financial=80, risk=30, business=70, moat=60, geo=20)

    op = build_full_opinion("320193", "Test Co", ticker="TST")

    # financial .25 + (100-risk) .20 + business .20 + moat .15 + (100-geo) .20
    expected = clamp_overall_score(80 * 0.25 + 70 * 0.20 + 70 * 0.20 + 60 * 0.15 + 80 * 0.20)
    assert op["overall_score"] == expected == 73.0
    assert op["scores"] == {
        "financial": 80,
        "risk": 30,
        "business_model": 70,
        "moat": 60,
        "geopolitical": 20,
    }
    # CIK is zero-padded to 10 digits and the LLM layer degraded cleanly to None.
    assert op["company_cik"] == "0000320193"
    assert op["llm_analysis"] is None


def test_blend_inversion_more_risk_and_geo_lowers_score(monkeypatch):
    _patch_pipeline(monkeypatch, financial=50, risk=0, business=50, moat=50, geo=0)
    best = build_full_opinion("1", "C")["overall_score"]

    _patch_pipeline(monkeypatch, financial=50, risk=100, business=50, moat=50, geo=100)
    worst = build_full_opinion("1", "C")["overall_score"]

    assert best > worst


def test_blend_clamped_to_0_and_100(monkeypatch):
    _patch_pipeline(monkeypatch, financial=100, risk=0, business=100, moat=100, geo=0)
    assert build_full_opinion("1", "C")["overall_score"] == 100

    _patch_pipeline(monkeypatch, financial=0, risk=100, business=0, moat=0, geo=100)
    assert build_full_opinion("1", "C")["overall_score"] == 0


def test_llm_analysis_attached_when_available(monkeypatch):
    class FakeLLM:
        def model_dump(self):
            return {"enhanced_summary": "ai text"}

    _patch_pipeline(monkeypatch, financial=60, risk=40, business=60, moat=60, geo=30, llm=FakeLLM())
    op = build_full_opinion("1", "C")
    assert op["llm_analysis"] == {"enhanced_summary": "ai text"}


# --- pure presentation helpers --------------------------------------------

@pytest.mark.parametrize(
    "raw, expected",
    [(50.0, 50.0), (150, 100), (-10, 0), (73.456, 73.46), (100, 100), (0, 0)],
)
def test_clamp_overall_score(raw, expected):
    assert clamp_overall_score(raw) == expected


def test_build_strengths_thresholds():
    fin = {"total_financial_score": 80, "category_scores": {"cash_generation": 20}}
    bus = {"total_business_model_score": 85, "category_scores": {"ecosystem_strength": 12}}
    moat = {"total_moat_score": 80}
    strengths = build_strengths(fin, bus, moat)
    assert "Strong overall financial quality." in strengths
    assert any("business model" in s.lower() for s in strengths)
    assert any("moat" in s.lower() for s in strengths)
    assert len(strengths) <= 5


def test_build_strengths_empty_when_low():
    fin = {"total_financial_score": 10, "category_scores": {}}
    bus = {"total_business_model_score": 10, "category_scores": {}}
    moat = {"total_moat_score": 10}
    assert build_strengths(fin, bus, moat) == []


def test_build_weaknesses_thresholds_and_cap():
    fin = {"category_scores": {"leverage": 5, "balance_sheet_strength": 5}}
    risk = {"total_risk_score": 70}
    bus = {"category_scores": {"operational_intensity": 10, "customer_dependency": 10}}
    geo = {"total_geopolitical_score": 50}
    weaknesses = build_weaknesses(fin, risk, bus, geo)
    assert any("risk" in w.lower() for w in weaknesses)
    assert len(weaknesses) <= 5


def test_build_recent_changes_translates_changes():
    change = {
        "score_changes": {
            "risk": {"change": 5},
            "business_model": {"change": -3},
            "moat": {"change": 2},
        },
        "new_sentences": {"risk_factors": ["some newly added risk language"]},
    }
    changes = build_recent_changes(change)
    assert any("Risk score increased by 5" in c for c in changes)
    assert any("Business model score decreased by 3" in c for c in changes)
    assert any("Moat score increased by 2" in c for c in changes)
    assert any("new risk-factor language" in c for c in changes)
    assert len(changes) <= 5


def test_build_recent_changes_empty_when_no_data():
    assert build_recent_changes({"message": "not enough filings"}) == []
    assert build_recent_changes({}) == []


def test_write_summary_band_phrases():
    summary = write_summary(
        {"total_financial_score": 80},
        {"total_risk_score": 75},
        {"total_business_model_score": 85},
        {"total_moat_score": 80},
        ["StrengthOne"],
        ["WeaknessOne"],
        ["ChangeOne"],
        {"total_geopolitical_score": 60},
    )
    assert "financially strong" in summary
    assert "strong business model" in summary
    assert "strong moat" in summary
    assert "Risk disclosures are elevated" in summary
    assert "significantly adverse" in summary
    assert "Key strength: StrengthOne" in summary
    assert "Key weakness: WeaknessOne" in summary
    assert "Recent change: ChangeOne" in summary

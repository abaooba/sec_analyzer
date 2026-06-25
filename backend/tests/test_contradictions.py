"""Tests for the contradiction detector (opinion.detect_contradictions)."""

from backend.app.opinion import detect_contradictions


def _opinion(**overrides):
    base = {
        "overall_score": 50,
        "scores": {
            "financial": 50,
            "risk": 50,
            "business_model": 50,
            "moat": 50,
            "geopolitical": 50,
        },
        "forensic": {"flags": []},
        "confidence": {"level": "high"},
        "score_trajectory": {"trends": {}},
    }
    base.update(overrides)
    return base


def test_no_contradictions_when_coherent():
    assert detect_contradictions(_opinion()) == []


def test_high_overall_with_forensic_flags():
    notes = detect_contradictions(_opinion(overall_score=80, forensic={"flags": ["going_concern"]}))
    assert any("forensic red flag" in n.lower() for n in notes)


def test_strong_financial_but_low_confidence():
    op = _opinion(
        scores={"financial": 75, "risk": 50, "business_model": 50, "moat": 50, "geopolitical": 50},
        confidence={"level": "low"},
    )
    assert any("thin data" in n.lower() for n in detect_contradictions(op))


def test_low_risk_but_high_geopolitical():
    op = _opinion(
        scores={"financial": 50, "risk": 10, "business_model": 50, "moat": 50, "geopolitical": 60}
    )
    assert any("understated" in n.lower() for n in detect_contradictions(op))


def test_mixed_trajectory_business_up_risk_up():
    op = _opinion(
        score_trajectory={
            "trends": {
                "business_model": {"direction": "up", "change": 5},
                "risk": {"direction": "up", "change": 4},
            }
        }
    )
    assert any("mixed" in n.lower() for n in detect_contradictions(op))

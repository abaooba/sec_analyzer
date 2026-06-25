"""Tests for the CLI report's signature-signals formatter (main.format_signature_section)."""

from backend.main import format_signature_section


def test_formats_all_blocks():
    opinion = {
        "confidence": {"level": "high", "score": 85},
        "forensic": {"flags": ["going_concern", "restatement"]},
        "score_trajectory": {"trends": {"risk": {"direction": "up", "change": 5}}},
        "contradictions": ["High overall score despite forensic red flags."],
    }
    out = format_signature_section(opinion)
    assert "Analysis confidence: high (85/100)" in out
    assert "going concern" in out and "restatement" in out
    assert "risk up (+5)" in out
    assert "Contradictions / tensions:" in out
    assert "High overall score despite forensic red flags." in out


def test_handles_empty_opinion():
    out = format_signature_section({})
    # The forensic line always renders; the optional blocks are omitted.
    assert "Forensic red flags: none detected" in out
    assert "Analysis confidence" not in out
    assert "Contradictions" not in out

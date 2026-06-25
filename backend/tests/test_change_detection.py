"""Tests for the pure year-over-year change-detection helpers (change_detection).

detect_filing_changes (the DB-backed orchestrator) is exercised via test_opinion;
the pure set-difference + length-delta helpers are covered here.
"""

from backend.app.change_detection import (
    compare_section_lengths,
    get_new_sentences,
    split_into_sentences,
)


def test_split_into_sentences():
    assert split_into_sentences("First sentence. Second one! A third?  ") == [
        "First sentence.",
        "Second one!",
        "A third?",
    ]
    assert split_into_sentences("") == []


def test_get_new_sentences_is_set_difference():
    current = "We face tariff risk. Cloud revenue grew. Supply chain is stable."
    previous = "We face tariff risk. Supply chain is stable."
    new = get_new_sentences(current, previous)
    assert "Cloud revenue grew." in new
    assert "We face tariff risk." not in new  # unchanged sentences aren't "new"


def test_get_new_sentences_caps_output():
    current = " ".join(f"New sentence number {i}." for i in range(50))
    assert len(get_new_sentences(current, "", max_sentences=10)) == 10


def test_compare_section_lengths_reports_deltas():
    result = compare_section_lengths(
        {"business": "abcdef", "risk_factors": "xy", "mdna": ""},
        {"business": "abc", "risk_factors": "xyz", "mdna": ""},
    )
    assert result["business"]["length_change"] == 3      # 6 - 3
    assert result["risk_factors"]["length_change"] == -1  # 2 - 3
    assert result["mdna"]["length_change"] == 0
    assert result["business"]["current_length"] == 6

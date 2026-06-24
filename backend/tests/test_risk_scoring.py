"""Tests for the risk scorer — the archetype text scorer.

Focus areas (per the safety-net backlog):
  * `soften_count` bucket boundaries (the diminishing-returns dampening that all
    keyword scorers rely on),
  * keyword counting / sentence splitting helpers,
  * `score_risk_text` end-to-end on a known string (structure + evidence).
"""

import pytest

from backend.app.scoring.risk import (
    CATEGORY_CAP,
    count_keyword_matches,
    normalize_text,
    score_risk_text,
    soften_count,
    split_into_sentences,
)


@pytest.mark.parametrize(
    "count, expected",
    [
        (-5, 0),   # guard: negative never happens, but must not blow up
        (0, 0),
        (1, 1),
        (2, 1),    # 1-2 -> 1
        (3, 2),
        (4, 2),
        (5, 2),    # 3-5 -> 2
        (6, 3),
        (40, 3),   # 6+ -> 3 (a term repeated 40x can't dominate)
    ],
)
def test_soften_count_buckets(count, expected):
    assert soften_count(count) == expected


def test_count_keyword_matches_counts_all_occurrences():
    text = "tariffs and more tariffs and yet more tariffs"
    assert count_keyword_matches(r"\btariffs\b", text) == 3
    assert count_keyword_matches(r"\bsanctions\b", text) == 0


def test_normalize_text_lowercases_and_handles_empty():
    assert normalize_text("Supply CHAIN") == "supply chain"
    assert normalize_text("") == ""
    assert normalize_text(None) == ""


def test_split_into_sentences():
    text = "First sentence. Second one! A third?  Trailing"
    sentences = split_into_sentences(text)
    assert sentences == ["First sentence.", "Second one!", "A third?", "Trailing"]
    assert split_into_sentences("") == []


def test_score_risk_text_on_known_keywords():
    text = (
        "Our supply chain faces disruption and component shortages. "
        "Tariffs and geopolitical tensions in China could raise costs. "
        "A cybersecurity data breach could harm operations. "
        "We depend on a limited number of customers."
    )
    result = score_risk_text(text)

    # Structure contract the rest of the pipeline relies on.
    assert set(result) >= {
        "total_risk_score",
        "category_scores",
        "matched_keywords",
        "evidence_sentences",
    }

    # Several risk categories should have fired.
    assert result["total_risk_score"] > 0
    assert result["category_scores"]["supply_chain"] > 0
    assert result["category_scores"]["geopolitical"] > 0
    assert result["category_scores"]["cybersecurity"] > 0

    # No single category may exceed the per-category cap.
    assert all(score <= CATEGORY_CAP for score in result["category_scores"].values())

    # Evidence sentences are surfaced for the supply-chain hit.
    assert any("supply chain" in s.lower() for s in result["evidence_sentences"]["supply_chain"])


def test_score_risk_text_empty_is_zero():
    result = score_risk_text("")
    assert result["total_risk_score"] == 0
    assert all(score == 0 for score in result["category_scores"].values())


def test_score_risk_text_caps_repeated_term():
    """A term repeated far more often must not produce an unbounded score:
    softening (6+ -> 3) and the per-category cap keep it bounded."""
    spammy = "inflation " * 200
    result = score_risk_text(spammy)
    assert result["category_scores"]["macroeconomic"] <= CATEGORY_CAP

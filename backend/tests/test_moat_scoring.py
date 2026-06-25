"""Tests for the moat scorer (score_moat_text).

Score = BASE_SCORE (35) + sum of weighted, per-category-capped contributions,
clamped to [0, 100]. Higher = wider moat. Keywords/weights come from keywords.toml.
"""

from backend.app.scoring.moat import BASE_SCORE, score_moat_text


def test_neutral_text_scores_at_baseline():
    result = score_moat_text("The weather was pleasant and lunch was served.")
    assert result["total_moat_score"] == BASE_SCORE


def test_moat_keywords_raise_score_above_baseline():
    text = (
        "Our patent portfolio, proprietary process technology, and trademark brand "
        "create high barriers to entry and deep ecosystem strength."
    )
    result = score_moat_text(text)
    assert result["total_moat_score"] > BASE_SCORE


def test_score_stays_within_bounds_under_heavy_repetition():
    text = "patent proprietary brand ecosystem scale barriers to entry switching costs " * 40
    result = score_moat_text(text)
    assert 0 <= result["total_moat_score"] <= 100

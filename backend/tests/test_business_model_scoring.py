"""Tests for the two-sided business-model scorer (score_business_model_text).

Score = BASE_SCORE (50) + capped positive contributions − capped negatives,
clamped to [0, 100]. Keywords/weights come from keywords.toml.
"""

from backend.app.scoring.business_model import BASE_SCORE, score_business_model_text


def test_neutral_text_scores_at_baseline():
    result = score_business_model_text("The weather was pleasant and lunch was served.")
    assert result["total_business_model_score"] == BASE_SCORE
    assert result["positive_contribution"] == 0
    assert result["negative_contribution"] == 0


def test_positive_traits_raise_score_above_baseline():
    text = (
        "Our subscription and recurring fee-based revenue from aftermarket "
        "consumables and spare parts grows steadily."
    )
    result = score_business_model_text(text)
    assert result["positive_contribution"] > 0
    assert result["negative_contribution"] == 0
    assert result["total_business_model_score"] > BASE_SCORE


def test_negative_traits_lower_score_below_baseline():
    text = (
        "Our manufacturing and assembly operations are capital intensive, with heavy "
        "logistics, inventory, and many facilities."
    )
    result = score_business_model_text(text)
    assert result["negative_contribution"] > 0
    assert result["total_business_model_score"] < BASE_SCORE


def test_score_stays_within_bounds_under_heavy_repetition():
    text = "manufacturing assembly supplier logistics inventory component distribution facility " * 30
    result = score_business_model_text(text)
    assert 0 <= result["total_business_model_score"] <= 100

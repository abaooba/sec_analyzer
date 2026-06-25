"""Tests for the analysis confidence meta-score (opinion.compute_analysis_confidence).

Confidence reflects how much real data backs an opinion, so a thin/data-starved
analysis isn't mistaken for a strong one.
"""

from backend.app.opinion import compute_analysis_confidence


def _full_sections():
    return {
        "risk_factors": "risk text",
        "business": "business text",
        "mdna": "mdna text",
        "full_text": "x",
    }


def test_full_data_is_high_confidence():
    result = compute_analysis_confidence(
        sections=_full_sections(),
        financial_result={
            "metrics_used": {
                "revenue": 1,
                "net_income": 2,
                "operating_margin": 0.1,
                "operating_cash_flow": 3,
                "total_debt": 4,
            }
        },
        change_result={"score_changes": {}},  # no "message" -> YoY present
        geopolitical_result={"article_count": 12},
    )
    assert result["score"] == 100
    assert result["level"] == "high"
    assert result["factors"]["risk_factors_text"] is True
    assert result["factors"]["financial_metrics_present"] == 5
    assert result["factors"]["year_over_year_data"] is True
    assert result["factors"]["news_articles_analyzed"] == 12


def test_no_data_is_low_confidence():
    result = compute_analysis_confidence(
        sections={},
        financial_result={"metrics_used": {}},
        change_result={"message": "Not enough annual filings found to compare."},
        geopolitical_result={"article_count": 0},
    )
    assert result["score"] == 0
    assert result["level"] == "low"
    assert result["factors"]["risk_factors_text"] is False
    assert result["factors"]["year_over_year_data"] is False


def test_filing_text_only_is_moderate():
    result = compute_analysis_confidence(
        sections=_full_sections(),  # 25 + 20 + 10 = 55
        financial_result={"metrics_used": {"revenue": None}},  # 0 present
        change_result={"message": "bailed"},  # no YoY
        geopolitical_result={"article_count": 0},
    )
    assert result["score"] == 55
    assert result["level"] == "moderate"


def test_none_metrics_do_not_count_and_inputs_are_defensive():
    # None-valued metrics shouldn't count; empty/odd inputs shouldn't blow up.
    result = compute_analysis_confidence(
        sections={"risk_factors": None},
        financial_result={"metrics_used": {"revenue": None, "net_income": 5}},
        change_result={},  # empty -> no YoY
        geopolitical_result={},
    )
    assert result["factors"]["financial_metrics_present"] == 1
    assert result["factors"]["risk_factors_text"] is False
    assert result["score"] == 4  # 1 metric * 4, nothing else

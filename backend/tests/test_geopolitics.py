"""Tests for the geopolitics scorer's pure news-classification helpers.

The fusion score itself (score_geopolitical_impact) does network + DB, but its
building blocks — keyword counting, article-text assembly, and news classification
into categories — are pure and covered here offline.
"""

from backend.app.scoring.geopolitics import (
    build_article_text,
    classify_articles,
    count_keywords,
    matches_any_pattern,
    soften_count,
)


def test_build_article_text_combines_fields():
    article = {"title": "Tariffs rise", "summary": "China trade", "full_text": "supply chain"}
    assert build_article_text(article) == "Tariffs rise China trade supply chain"
    # Missing fields default to "" rather than blowing up.
    assert build_article_text({"title": "Only title"}) == "Only title  "


def test_soften_count_buckets():
    assert [soften_count(n) for n in (0, 1, 2, 3, 5, 6, 50)] == [0, 1, 1, 2, 2, 3, 3]


def test_matches_any_pattern():
    assert matches_any_pattern("a tariff war looms", [r"\btariff\b", r"\bwar\b"])
    assert not matches_any_pattern("calm seas", [r"\btariff\b"])


def test_count_keywords_softens_per_category():
    keyword_map = {"trade": [r"\btariff\b", r"\bsanction\b"], "war": [r"\bwar\b"]}
    text = "Tariff tariff TARIFF and a sanction; no conflict here."
    results = count_keywords(text, keyword_map)
    # 'tariff' x3 -> softened 2; 'sanction' x1 -> softened 1; trade softened total = 3.
    assert results["trade"]["raw_total_hits"] == 4
    assert results["trade"]["softened_total_hits"] == 3
    assert results["war"]["raw_total_hits"] == 0


def test_classify_articles_tallies_and_caps_evidence():
    articles = [
        {"title": "New tariffs on imports", "summary": "", "link": "l1", "source": "s"}
        for _ in range(7)
    ]
    result = classify_articles(articles)
    assert result["category_counts"]["tariffs_trade"] == 7  # all 7 counted
    assert len(result["category_articles"]["tariffs_trade"]) == 5  # evidence capped at 5
    assert result["category_counts"]["middle_east_energy_shipping"] == 0  # unrelated stays 0

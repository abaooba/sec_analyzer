"""Business-model quality scoring from the Business/MD&A text.

Same keyword machinery as risk.py, but with a twist: this score starts from a
neutral BASE_SCORE (50) and moves UP for desirable traits (recurring revenue,
diversification, scalability, ecosystem strength) and DOWN for undesirable ones
(operational intensity, customer dependency). So it's a two-sided meter where
50 = "average business model".
"""

import re

from ._keyword_config import scorer_config

# Keyword regex patterns, the positive/negative category weights, caps, and the
# neutral base score all load from keywords.toml (via _keyword_config) so they can
# be tuned/generalized without touching code. Module-level names are unchanged, so
# the rest of this file (the two-sided scoring) is intact.
_CFG = scorer_config("business_model")
BUSINESS_MODEL_KEYWORDS: dict[str, list[str]] = _CFG["keywords"]
POSITIVE_WEIGHTS: dict[str, float] = _CFG["positive_weights"]
NEGATIVE_WEIGHTS: dict[str, float] = _CFG["negative_weights"]
POSITIVE_CAP: int = _CFG["positive_cap"]
NEGATIVE_CAP: int = _CFG["negative_cap"]
TOTAL_CAP: int = _CFG["total_cap"]
BASE_SCORE: int = _CFG["base_score"]


def normalize_text(text: str) -> str:
    if not text:
        return ""
    return text.lower()


def count_keyword_matches(pattern: str, text: str) -> int:
    return len(re.findall(pattern, text))


def soften_count(count: int) -> int:
    if count <= 0:
        return 0
    if count <= 2:
        return 1
    if count <= 5:
        return 2
    return 3


def split_into_sentences(text: str) -> list[str]:
    if not text:
        return []

    text = re.sub(r"\s+", " ", text).strip()
    sentences = re.split(r"(?<=[.!?])\s+", text)

    return [sentence.strip() for sentence in sentences if sentence.strip()]


def count_business_keywords(business_text: str) -> dict:
    text = normalize_text(business_text)
    results = {}

    for category, keywords in BUSINESS_MODEL_KEYWORDS.items():
        keyword_hits = {}
        raw_total = 0
        softened_total = 0

        for keyword in keywords:
            count = count_keyword_matches(keyword, text)
            if count > 0:
                keyword_hits[keyword] = count
                raw_total += count
                softened_total += soften_count(count)

        results[category] = {
            "raw_total_hits": raw_total,
            "softened_total_hits": softened_total,
            "keyword_hits": keyword_hits,
        }

    return results


def extract_business_sentences(business_text: str, max_sentences_per_category: int = 3) -> dict:
    sentences = split_into_sentences(business_text)
    category_sentences: dict[str, list[str]] = {category: [] for category in BUSINESS_MODEL_KEYWORDS.keys()}

    for sentence in sentences:
        normalized_sentence = sentence.lower()

        for category, keywords in BUSINESS_MODEL_KEYWORDS.items():
            if len(category_sentences[category]) >= max_sentences_per_category:
                continue

            for keyword in keywords:
                if re.search(keyword, normalized_sentence):
                    if sentence not in category_sentences[category]:
                        category_sentences[category].append(sentence)
                    break

    return category_sentences


def score_business_model_text(business_text: str) -> dict:
    """Score = 50 + (capped positive contributions) - (capped negatives)."""
    keyword_results = count_business_keywords(business_text)
    evidence_sentences = extract_business_sentences(business_text)

    category_scores = {}
    matched_keywords = {}
    total_positive = 0
    total_negative = 0

    # Route each category to the positive or negative tally based on its type.
    for category, result in keyword_results.items():
        softened_hits = result["softened_total_hits"]
        matched_keywords[category] = result["keyword_hits"]

        if category in POSITIVE_WEIGHTS:
            weighted_score = softened_hits * POSITIVE_WEIGHTS[category]
            category_score = min(round(weighted_score, 2), POSITIVE_CAP)
            total_positive += category_score
        else:
            weighted_score = softened_hits * NEGATIVE_WEIGHTS[category]
            category_score = min(round(weighted_score, 2), NEGATIVE_CAP)
            total_negative += category_score

        category_scores[category] = category_score

    # Combine around the neutral base and clamp to [0, 100].
    total_score = BASE_SCORE + total_positive - total_negative
    total_score = max(0, min(round(total_score, 2), TOTAL_CAP))

    return {
        "total_business_model_score": total_score,
        "category_scores": category_scores,
        "matched_keywords": matched_keywords,
        "evidence_sentences": evidence_sentences,
        "details": keyword_results,
        "positive_contribution": round(total_positive, 2),
        "negative_contribution": round(total_negative, 2),
    }

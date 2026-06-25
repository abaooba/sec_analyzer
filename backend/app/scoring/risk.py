"""Risk scoring by keyword analysis of a filing's Risk Factors text.

This is the archetype for all the text-based scorers (business_model, moat,
geopolitics follow the same shape):

  1. A dict of CATEGORIES -> list of regex keyword patterns.
  2. Count how often each pattern appears, then "soften" raw counts so a section
     that says "tariff" 40 times doesn't dwarf one that says it twice (the score
     is about *presence/emphasis*, not raw frequency).
  3. Weight each category and sum into a capped total.
  4. Separately, pull a few example sentences per category as human-readable
     "evidence" (also fed to the LLM later).

Higher risk score = MORE risk language in the filing (it's a risk meter, so in
the final opinion it's inverted: 100 - risk).
"""

import re

from ._keyword_config import scorer_config

# Keyword regex patterns, category weights, and caps are loaded from keywords.toml
# (via _keyword_config) so they can be tuned/generalized without touching code.
# The module-level names below are unchanged, so the rest of this file is intact.
_CFG = scorer_config("risk")
RISK_KEYWORDS: dict[str, list[str]] = _CFG["keywords"]
RISK_WEIGHTS: dict[str, float] = _CFG["weights"]
CATEGORY_CAP: int = _CFG["category_cap"]
TOTAL_CAP: int = _CFG["total_cap"]


def normalize_text(text: str) -> str:
    """Lowercase the text so keyword matching is case-insensitive."""
    if not text:
        return ""
    return text.lower()


def count_keyword_matches(pattern: str, text: str) -> int:
    """How many times a regex pattern occurs in the text."""
    return len(re.findall(pattern, text))


def soften_count(count: int) -> int:
    """Dampen raw counts into 0..3 buckets (diminishing returns).

    0 -> 0, 1-2 -> 1, 3-5 -> 2, 6+ -> 3. This stops one heavily-repeated term
    from dominating; we care that a topic is present and emphasized, not the
    literal occurrence count.
    """
    if count <= 0:
        return 0
    if count <= 2:
        return 1
    if count <= 5:
        return 2
    return 3


def count_risk_keywords(risk_text: str) -> dict:
    """Count + soften keyword hits for every risk category."""
    text = normalize_text(risk_text)
    results = {}

    for category, keywords in RISK_KEYWORDS.items():
        keyword_hits = {}
        softened_total = 0
        raw_total = 0

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


def score_risk_text(risk_text: str) -> dict:
    """Top-level: produce the risk score + breakdown + evidence for one filing."""
    keyword_results = count_risk_keywords(risk_text)
    evidence_sentences = extract_risk_sentences(risk_text)

    category_scores = {}
    matched_keywords = {}
    total_score = 0

    # score = softened_hits * category_weight, capped per category, then summed.
    for category, result in keyword_results.items():
        softened_hits = result["softened_total_hits"]
        weight = RISK_WEIGHTS.get(category, 1.0)

        weighted_score = softened_hits * weight
        category_score = min(round(weighted_score, 2), CATEGORY_CAP)

        category_scores[category] = category_score
        matched_keywords[category] = result["keyword_hits"]

        total_score += category_score

    total_score = min(round(total_score, 2), TOTAL_CAP)

    return {
        "total_risk_score": total_score,
        "category_scores": category_scores,
        "matched_keywords": matched_keywords,
        "details": keyword_results,
        "evidence_sentences": evidence_sentences,
    }

def split_into_sentences(text: str) -> list[str]:
    """Naive sentence splitter: break after . ! ? followed by whitespace.

    `(?<=[.!?])` is a lookbehind — it splits *after* the punctuation without
    consuming it. Good enough for evidence extraction (not perfect grammar).
    """
    if not text:
        return []

    text = re.sub(r"\s+", " ", text).strip()
    sentences = re.split(r"(?<=[.!?])\s+", text)

    return [sentence.strip() for sentence in sentences if sentence.strip()]


def extract_risk_sentences(risk_text: str, max_sentences_per_category: int = 3) -> dict:
    """Collect up to N example sentences per category that contain a keyword.

    These become the "evidence sentences" surfaced to the user and handed to the
    LLM so its narrative can cite real language from the filing.
    """
    sentences = split_into_sentences(risk_text)
    category_sentences: dict[str, list[str]] = {category: [] for category in RISK_KEYWORDS.keys()}

    for sentence in sentences:
        normalized_sentence = sentence.lower()

        for category, keywords in RISK_KEYWORDS.items():
            if len(category_sentences[category]) >= max_sentences_per_category:
                continue

            for keyword in keywords:
                if re.search(keyword, normalized_sentence):
                    if sentence not in category_sentences[category]:
                        category_sentences[category].append(sentence)
                    break

    return category_sentences

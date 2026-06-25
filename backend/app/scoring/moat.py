"""Economic-moat scoring — how defensible is the company's competitive position.

"Moat" is Buffett-speak for durable competitive advantage. Same keyword engine
as the other text scorers, starting from BASE_SCORE = 35 and adding points for
each moat source detected: brand, switching costs, ecosystem lock-in, scale,
distribution, IP/patents, customer lock-in, and technology leadership. IP and
tech-leadership carry the heaviest weights (1.6). Higher = wider moat.

(Many keywords here are tuned toward semiconductor/equipment language — e.g.
"euv", "process node", "photolithography" — reflecting the filings this was
developed against.)
"""

import re

from ._keyword_config import scorer_config

# Keyword regex patterns, weights, caps, and the base score are loaded from
# keywords.toml (via _keyword_config) so they can be tuned/generalized without
# touching code. Module-level names are unchanged, so the rest of this file is
# intact. (Many moat keywords lean toward semiconductor/equipment language —
# generalizing them is now a data-file edit, not a code change.)
_CFG = scorer_config("moat")
MOAT_KEYWORDS: dict[str, list[str]] = _CFG["keywords"]
MOAT_WEIGHTS: dict[str, float] = _CFG["weights"]
CATEGORY_CAP: int = _CFG["category_cap"]
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


def count_moat_keywords(business_text: str) -> dict:
    text = normalize_text(business_text)
    results = {}

    for category, keywords in MOAT_KEYWORDS.items():
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


def extract_moat_sentences(business_text: str, max_sentences_per_category: int = 3) -> dict:
    sentences = split_into_sentences(business_text)
    category_sentences: dict[str, list[str]] = {category: [] for category in MOAT_KEYWORDS.keys()}

    for sentence in sentences:
        normalized_sentence = sentence.lower()

        for category, keywords in MOAT_KEYWORDS.items():
            if len(category_sentences[category]) >= max_sentences_per_category:
                continue

            for keyword in keywords:
                if re.search(keyword, normalized_sentence):
                    if sentence not in category_sentences[category]:
                        category_sentences[category].append(sentence)
                    break

    return category_sentences


def score_moat_text(business_text: str) -> dict:
    """Score = 35 baseline + sum of weighted, capped moat-category contributions."""
    keyword_results = count_moat_keywords(business_text)
    evidence_sentences = extract_moat_sentences(business_text)

    category_scores = {}
    matched_keywords = {}
    total_score = BASE_SCORE  # start at the baseline and accumulate upward

    for category, result in keyword_results.items():
        softened_hits = result["softened_total_hits"]
        weight = MOAT_WEIGHTS.get(category, 1.0)

        weighted_score = softened_hits * weight
        category_score = min(round(weighted_score, 2), CATEGORY_CAP)

        category_scores[category] = category_score
        matched_keywords[category] = result["keyword_hits"]
        total_score += category_score

    total_score = max(0, min(round(total_score, 2), TOTAL_CAP))

    return {
        "total_moat_score": total_score,
        "category_scores": category_scores,
        "matched_keywords": matched_keywords,
        "evidence_sentences": evidence_sentences,
        "details": keyword_results,
    }

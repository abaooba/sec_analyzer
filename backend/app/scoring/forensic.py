"""Forensic red-flag detection from filing text.

A keyword scorer (same engine as risk.py) tuned to accounting / disclosure red
flags an analyst wants surfaced explicitly: going-concern doubt, financial
restatements, material weaknesses in internal control, impairments / write-downs,
related-party dealings, liquidity / covenant stress, SEC investigations, and
auditor changes.

Unlike the five graded meters, this does NOT feed the weighted overall score — it
is surfaced as a discrete list of fired flags (with evidence sentences), so a real
red flag is never averaged away. Keyword patterns and weights live in
keywords.toml ([forensic]); the text-scoring primitives are reused from risk.py
(the archetype text scorer).
"""

import re

from ._keyword_config import scorer_config
from .risk import count_keyword_matches, normalize_text, soften_count, split_into_sentences

_CFG = scorer_config("forensic")
FORENSIC_KEYWORDS: dict[str, list[str]] = _CFG["keywords"]
FORENSIC_WEIGHTS: dict[str, float] = _CFG["weights"]
CATEGORY_CAP: int = _CFG["category_cap"]
TOTAL_CAP: int = _CFG["total_cap"]


def _evidence_sentences(sentences: list[str], patterns: list[str], limit: int) -> list[str]:
    """Up to `limit` distinct sentences that contain one of a flag's patterns."""
    found: list[str] = []
    for sentence in sentences:
        normalized = sentence.lower()
        if any(re.search(pattern, normalized) for pattern in patterns):
            if sentence not in found:
                found.append(sentence)
                if len(found) >= limit:
                    break
    return found


def score_forensic_text(text: str, max_sentences_per_flag: int = 2) -> dict:
    """Detect forensic red-flag language in a filing.

    Returns the fired `flags` (categories with at least one match), a 0-100
    `total_forensic_score` (higher = more / heavier red flags), per-category
    scores, the matched keywords, and a couple of evidence sentences per fired flag.
    """
    normalized_text = normalize_text(text)
    sentences = split_into_sentences(text)

    category_scores: dict[str, float] = {}
    matched_keywords: dict[str, dict] = {}
    evidence_sentences: dict[str, list[str]] = {}
    flags: list[str] = []
    total_score = 0.0

    for category, patterns in FORENSIC_KEYWORDS.items():
        hits: dict[str, int] = {}
        softened_total = 0
        for pattern in patterns:
            count = count_keyword_matches(pattern, normalized_text)
            if count > 0:
                hits[pattern] = count
                softened_total += soften_count(count)

        weight = FORENSIC_WEIGHTS.get(category, 1.0)
        category_score = min(round(softened_total * weight, 2), CATEGORY_CAP)
        category_scores[category] = category_score
        matched_keywords[category] = hits
        total_score += category_score

        if hits:
            flags.append(category)
            evidence_sentences[category] = _evidence_sentences(
                sentences, patterns, max_sentences_per_flag
            )

    total_score = min(round(total_score, 2), TOTAL_CAP)

    return {
        "total_forensic_score": total_score,
        "flags": flags,
        "category_scores": category_scores,
        "matched_keywords": matched_keywords,
        "evidence_sentences": evidence_sentences,
    }

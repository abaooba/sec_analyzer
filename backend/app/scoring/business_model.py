"""Business-model quality scoring from the Business/MD&A text.

Same keyword machinery as risk.py, but with a twist: this score starts from a
neutral BASE_SCORE (50) and moves UP for desirable traits (recurring revenue,
diversification, scalability, ecosystem strength) and DOWN for undesirable ones
(operational intensity, customer dependency). So it's a two-sided meter where
50 = "average business model".
"""

import re


# Categories split into "good" and "bad" traits (see POSITIVE/NEGATIVE_WEIGHTS).
BUSINESS_MODEL_KEYWORDS = {
    "recurring_revenue": [
        r"\bsubscription\b",
        r"\bsubscriptions\b",
        r"\bservices\b",
        r"\bservice\b",
        r"\blicensing\b",
        r"\blicense\b",
        r"\bmaintenance\b",
        r"\bsupport\b",
        r"\bcloud\b",
        r"fee-based",
        r"\brecurring\b",
        r"service agreement",
        r"long-term service",
        r"\bupgrade\b",
        r"aftermarket",
        r"spare parts",
        r"installed base",
        r"consumables",
    ],
    "diversification": [
        r"\bproducts\b",
        r"\bservices\b",
        r"\bsegments\b",
        r"\bgeographic\b",
        r"\binternational\b",
        r"\bportfolio\b",
        r"\bmultiple\b",
        r"\bvariety\b",
        r"line includes",
        r"\bofferings\b",
        r"end markets",
        r"\bapplications\b",
        r"product portfolio",
        r"customer base",
        r"\bregions\b",
    ],
    "scalability": [
        r"\bplatform\b",
        r"\bsoftware\b",
        r"\bdigital\b",
        r"\becosystem\b",
        r"\bonline\b",
        r"\bcloud\b",
        r"\bintegrated\b",
        r"\bservices\b",
        r"\bmodular\b",
        r"\bstandardized\b",
        r"\bautomation\b",
        r"productivity",
        r"global service network",
        r"service network",
        r"installed base",
    ],
    "ecosystem_strength": [
        r"\becosystem\b",
        r"\bintegrated\b",
        r"installed base",
        r"\bcompatibility\b",
        r"customer loyalty",
        r"\bbrand\b",
        r"customer collaboration",
        r"application support",
        r"supplier network",
        r"service network",
        r"\bworkflow\b",
        r"\bqualification\b",
    ],
    "operational_intensity": [
        r"\bmanufacturing\b",
        r"\bassembly\b",
        r"\bsupplier\b",
        r"\bsuppliers\b",
        r"\blogistics\b",
        r"\binventory\b",
        r"\bcomponent\b",
        r"\bdistribution\b",
        r"capital intensive",
        r"\bfacility\b",
        r"\bfacilities\b",
        r"production capacity",
        r"service organization",
    ],
    "customer_dependency": [
        r"depend on",
        r"depend significantly",
        r"single source",
        r"\bconcentration\b",
        r"\bchannel\b",
        r"\breseller\b",
        r"third-party",
        r"limited number of customers",
        r"\bkey customer\b",
        r"\btop customer\b",
        r"customer concentration",
        r"supplier concentration",
        r"sole supplier",
    ],
}

# Traits that ADD to the score (durable, high-quality business characteristics).
POSITIVE_WEIGHTS = {
    "recurring_revenue": 1.4,
    "diversification": 1.2,
    "scalability": 1.3,
    "ecosystem_strength": 1.5,
}

# Traits that SUBTRACT from the score (fragility / lower-quality characteristics).
NEGATIVE_WEIGHTS = {
    "operational_intensity": 1.0,
    "customer_dependency": 1.2,
}

POSITIVE_CAP = 15   # per positive category cap
NEGATIVE_CAP = 12   # per negative category cap
TOTAL_CAP = 100
BASE_SCORE = 50     # neutral starting point: final = 50 + positives - negatives


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

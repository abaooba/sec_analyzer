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


# Moat-source categories -> keyword patterns. More categories firing = wider moat.
MOAT_KEYWORDS = {
    "brand_strength": [
        r"\bbrand\b",
        r"customer loyalty",
        r"\breputation\b",
        r"\btrusted\b",
        r"\bpremium\b",
        r"market leader",
        r"technology leader",
        r"industry leader",
    ],
    "switching_costs": [
        r"\bintegrated\b",
        r"\bcompatibility\b",
        r"\binstalled base\b",
        r"\bcontinuity\b",
        r"qualification",
        r"qualified",
        r"process integration",
        r"\bworkflow\b",
        r"service agreement",
        r"field service",
        r"\bupgrade\b",
        r"productivity upgrade",
        r"customer roadmap",
        r"process node",
        r"co-development",
    ],
    "ecosystem_lock_in": [
        r"\becosystem\b",
        r"\bservices\b",
        r"\bintegrated\b",
        r"supplier ecosystem",
        r"service network",
        r"global service network",
        r"customer support",
        r"application support",
        r"installed base management",
    ],
    "scale_advantages": [
        r"\bglobal\b",
        r"\bscale\b",
        r"\bworldwide\b",
        r"\binternational\b",
        r"supply chain",
        r"large and complex",
        r"installed base",
        r"barriers to entry",
        r"high barriers to entry",
        r"capital intensive",
        r"engineering complexity",
        r"long development cycle",
        r"manufacturing precision",
        r"\blead time\b",
    ],
    "distribution_advantages": [
        r"direct sales",
        r"\bdistribution\b",
        r"\bchannel\b",
        r"global sales",
        r"customer relationships",
        r"long-term customer",
        r"strategic customer",
        r"service organization",
    ],
    "intellectual_property": [
        r"intellectual property",
        r"\bpatent\b",
        r"\bpatents\b",
        r"\bproprietary\b",
        r"\btrademark\b",
        r"\bcopyright\b",
        r"patent portfolio",
        r"trade secret",
        r"know-how",
        r"licensed technology",
        r"process technology",
        r"proprietary process",
        r"photolithography",
        r"\beuv\b",
        r"extreme ultraviolet",
        r"high-na",
    ],
    "customer_dependency_lock_in": [
        r"sole supplier",
        r"single supplier",
        r"critical equipment",
        r"mission critical",
        r"\byield\b",
        r"\bthroughput\b",
        r"\buptime\b",
        r"qualification cycle",
        r"\bvalidated\b",
        r"replacement cycle",
    ],
    "technology_leadership": [
        r"technology leadership",
        r"technology leader",
        r"process roadmap",
        r"next-generation",
        r"advanced node",
        r"\br&d\b",
        r"research and development",
        r"\binnovation\b",
        r"roadmap",
        r"development program",
    ],
}

MOAT_WEIGHTS = {
    "brand_strength": 1.4,
    "switching_costs": 1.5,
    "ecosystem_lock_in": 1.2,
    "scale_advantages": 1.4,
    "distribution_advantages": 1.1,
    "intellectual_property": 1.6,
    "customer_dependency_lock_in": 1.5,
    "technology_leadership": 1.6,
}

CATEGORY_CAP = 15
TOTAL_CAP = 100
BASE_SCORE = 35   # every company starts with a small assumed baseline moat


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

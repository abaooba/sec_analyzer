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


# Each risk category maps to regex patterns. `\b` is a word boundary so
# `\binflation\b` matches "inflation" but not "inflationary-something-else".
RISK_KEYWORDS = {
    "macroeconomic": [
        r"\binflation\b",
        r"interest rates",
        r"\brecession\b",
        r"currency fluctuations",
        r"foreign exchange",
        r"exchange rates",
        r"economic conditions",
        r"consumer confidence",
        r"\bspending\b",
        r"\bmacroeconomic\b",
        r"cyclical demand",
        r"pricing pressure",
        r"adverse market conditions",
    ],
    "supply_chain": [
        r"supply chain",
        r"\bsupplier\b",
        r"\bsuppliers\b",
        r"\bmanufacturing\b",
        r"\bassembly\b",
        r"component shortages",
        r"\blogistics\b",
        r"\bdisruption\b",
        r"\bshortages\b",
        r"lead times",
        r"capacity constraints",
        r"raw materials",
        r"production interruption",
        r"single source supplier",
    ],
    "geopolitical": [
        r"\bgeopolitical\b",
        r"\btariffs\b",
        r"trade restrictions",
        r"trade tensions",
        r"\bsanctions\b",
        r"export controls",
        r"\bchina\b",
        r"\bchinese\b",
        r"\btaiwan\b",
        r"\bwar\b",
        r"armed conflict",
        r"international operations",
        r"cross-border operations",
        r"regional economic conditions",
        r"national security",
        r"customs duties",
    ],
    "regulatory_legal": [
        r"\bregulation\b",
        r"\bregulatory\b",
        r"\blitigation\b",
        r"\blawsuit\b",
        r"\bcompliance\b",
        r"\bantitrust\b",
        r"\bgovernment\b",
        r"legal proceedings",
        r"licensing restrictions",
        r"export license",
        r"data protection",
        r"environmental regulation",
        r"\btax law\b",
    ],
    "cybersecurity": [
        r"\bcybersecurity\b",
        r"cyber attack",
        r"cyber attacks",
        r"data breach",
        r"\bprivacy\b",
        r"security incident",
        r"unauthorized access",
        r"information security",
        r"\bransomware\b",
        r"network intrusion",
    ],
    "concentration": [
        r"single source",
        r"\bconcentration\b",
        r"depend significantly",
        r"majority of",
        r"customer concentration",
        r"supplier concentration",
        r"depend on",
        r"limited number of customers",
        r"\bkey customer\b",
        r"\btop customer\b",
        r"significant customer",
    ],
}

# How much each category contributes — geopolitical/supply-chain risks are
# weighted more heavily than generic macro risk.
RISK_WEIGHTS = {
    "macroeconomic": 1.0,
    "supply_chain": 1.2,
    "geopolitical": 1.4,
    "regulatory_legal": 1.1,
    "cybersecurity": 1.0,
    "concentration": 1.2,
}

CATEGORY_CAP = 15   # max points any single category can add
TOTAL_CAP = 100     # overall score ceiling


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
    category_sentences = {category: [] for category in RISK_KEYWORDS.keys()}

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

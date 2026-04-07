import re


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

RISK_WEIGHTS = {
    "macroeconomic": 1.0,
    "supply_chain": 1.2,
    "geopolitical": 1.4,
    "regulatory_legal": 1.1,
    "cybersecurity": 1.0,
    "concentration": 1.2,
}

CATEGORY_CAP = 15
TOTAL_CAP = 100


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


def count_risk_keywords(risk_text: str) -> dict:
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
    keyword_results = count_risk_keywords(risk_text)
    evidence_sentences = extract_risk_sentences(risk_text)

    category_scores = {}
    matched_keywords = {}
    total_score = 0

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
    if not text:
        return []

    text = re.sub(r"\s+", " ", text).strip()
    sentences = re.split(r"(?<=[.!?])\s+", text)

    return [sentence.strip() for sentence in sentences if sentence.strip()]


def extract_risk_sentences(risk_text: str, max_sentences_per_category: int = 3) -> dict:
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

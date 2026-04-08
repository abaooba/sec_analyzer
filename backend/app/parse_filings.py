from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable

from sqlalchemy import select

from frontend.app.db import SessionLocal
from frontend.app.models import Filing


ANNUAL_FORMS = ("20-F", "10-K", "40-F")
INTERIM_FORMS = ("10-Q", "6-K", "8-K")
DEFAULT_PREFERRED_FORMS = ANNUAL_FORMS + INTERIM_FORMS


def load_filing_html(local_path: str | None) -> str:
    if not local_path:
        return ""

    path = Path(local_path)
    if not path.exists():
        return ""

    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return ""


def filing_html_to_text(html: str) -> str:
    if not html:
        return ""

    text = html
    text = re.sub(r"(?is)<script.*?>.*?</script>", " ", text)
    text = re.sub(r"(?is)<style.*?>.*?</style>", " ", text)
    text = re.sub(r"(?is)<head.*?>.*?</head>", " ", text)

    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</p>", "\n", text)
    text = re.sub(r"(?i)</div>", "\n", text)
    text = re.sub(r"(?i)</tr>", "\n", text)
    text = re.sub(r"(?i)</li>", "\n", text)

    text = re.sub(r"(?is)<[^>]+>", " ", text)

    html_entities = {
        "&nbsp;": " ",
        "&amp;": "&",
        "&lt;": "<",
        "&gt;": ">",
        "&#160;": " ",
        "&#8217;": "'",
        "&#8220;": '"',
        "&#8221;": '"',
        "&#8211;": "-",
        "&#8212;": "-",
    }
    for k, v in html_entities.items():
        text = text.replace(k, v)

    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n\n", text)

    return text.strip()


def _normalize_text(text: str) -> str:
    if not text:
        return ""
    return re.sub(r"\s+", " ", text).strip()


def _extract_section_candidate(
    text: str,
    start_index: int,
    end_patterns: Iterable[str],
    *,
    max_chars: int,
    min_end_search_offset: int = 500,
) -> str:
    search_region = text[start_index : start_index + max_chars]
    if not search_region:
        return ""

    end_index_relative = None
    search_offset = min(min_end_search_offset, len(search_region))

    for pattern in end_patterns:
        match = re.search(pattern, search_region[search_offset:], flags=re.IGNORECASE)
        if match:
            candidate = search_offset + match.start()
            if end_index_relative is None or candidate < end_index_relative:
                end_index_relative = candidate

    if end_index_relative is None:
        section = search_region
    else:
        section = search_region[:end_index_relative]

    return _normalize_text(section)


def _find_section(
    text: str,
    start_patterns: Iterable[str],
    end_patterns: Iterable[str],
    *,
    max_chars: int = 250_000,
    min_words: int = 150,
) -> str:
    if not text:
        return ""

    start_matches = []
    for pattern in start_patterns:
        start_matches.extend(re.finditer(pattern, text, flags=re.IGNORECASE))

    if not start_matches:
        return ""

    candidates = []
    seen_starts = []

    for match in sorted(start_matches, key=lambda item: item.start()):
        start_index = match.start()

        if any(abs(start_index - seen_start) < 250 for seen_start in seen_starts):
            continue

        section = _extract_section_candidate(
            text,
            start_index,
            end_patterns,
            max_chars=max_chars,
        )
        if not section:
            continue

        candidates.append(
            {
                "start_index": start_index,
                "text": section,
                "word_count": len(section.split()),
            }
        )
        seen_starts.append(start_index)

    if not candidates:
        return ""

    substantive_candidates = [
        candidate for candidate in candidates
        if candidate["word_count"] >= min_words
    ]

    ranked_candidates = substantive_candidates or candidates
    best_candidate = max(
        ranked_candidates,
        key=lambda candidate: (candidate["word_count"], candidate["start_index"]),
    )
    return best_candidate["text"]


def _extract_business(text: str) -> str:
    start_patterns = [
        r"\bitem\s*1[\.\-:\s]+business\b",
        r"\bitem\s*4[\.\-:\s]+information on the company\b",
        r"\bbusiness overview\b",
        r"\binformation on the company\b",
        r"\bcompany overview\b",
        r"\bour business\b",
        r"\bstrategic report\b",
    ]
    end_patterns = [
        r"\bitem\s*1a\b",
        r"\brisk factors\b",
        r"\bitem\s*1b\b",
        r"\bitem\s*2\b",
        r"\bitem\s*4a\b",
        r"\bitem\s*5\b",
        r"\boperating and financial review\b",
        r"\bmanagement[’'`s\s]+discussion and analysis\b",
        r"\bresults of operations\b",
    ]
    return _find_section(text, start_patterns, end_patterns)


def _extract_risk_factors(text: str) -> str:
    start_patterns = [
        r"\bitem\s*1a[\.\-:\s]+risk factors\b",
        r"\bitem\s*3d[\.\-:\s]+risk factors\b",
        r"\brisk factors\b",
        r"\bprincipal risks\b",
        r"\bkey risks\b",
    ]
    end_patterns = [
        r"\bitem\s*1b\b",
        r"\bitem\s*2\b",
        r"\bitem\s*4\b",
        r"\binformation on the company\b",
        r"\bunresolved staff comments\b",
        r"\bproperties\b",
        r"\boperating and financial review\b",
        r"\bmanagement[’'`s\s]+discussion and analysis\b",
        r"\bfinancial review\b",
    ]
    return _find_section(text, start_patterns, end_patterns)


def _extract_mdna(text: str) -> str:
    start_patterns = [
        r"\bmanagement[’'`s\s]+discussion and analysis\b",
        r"\boperating and financial review\b",
        r"\boperating and financial review and prospects\b",
        r"\bmanagement[’'`s\s]+discussion\b",
        r"\bresults of operations\b",
        r"\bfinancial review\b",
    ]
    end_patterns = [
        r"\bquantitative and qualitative disclosures\b",
        r"\bitem\s*3\b",
        r"\bitem\s*4\b",
        r"\bitem\s*6\b",
        r"\bdirectors, senior management and employees\b",
        r"\bboard practices\b",
        r"\bfinancial statements\b",
        r"\bconsolidated financial statements\b",
    ]
    return _find_section(text, start_patterns, end_patterns)


def extract_key_sections(text: str) -> dict:
    business = _extract_business(text)
    risk_factors = _extract_risk_factors(text)
    mdna = _extract_mdna(text)

    return {
        "business": business,
        "risk_factors": risk_factors,
        "mdna": mdna,
        "full_text": text or "",
    }


def _pick_best_filing(cik: str, preferred_forms: Iterable[str]) -> Filing | None:
    preferred_forms = tuple(preferred_forms)

    with SessionLocal() as session:
        stmt = select(Filing).where(
            Filing.cik == cik,
            Filing.form.in_(preferred_forms),
        )
        filings = session.execute(stmt).scalars().all()

    if not filings:
        return None

    form_rank = {form: idx for idx, form in enumerate(preferred_forms)}

    def sort_key(filing: Filing):
        return (
            form_rank.get(filing.form, 999),
            -int(filing.filing_date.replace("-", "")) if filing.filing_date else -1,
            filing.accession_no or "",
        )

    filings.sort(key=sort_key)
    return filings[0]


def extract_latest_filing_sections(
    cik: str,
    preferred_forms: Iterable[str] = DEFAULT_PREFERRED_FORMS,
) -> dict:
    filing = _pick_best_filing(cik, preferred_forms)

    if filing is None:
        return {
            "form": None,
            "filing_date": None,
            "filing_url": None,
            "local_path": None,
            "business": "",
            "risk_factors": "",
            "mdna": "",
            "full_text": "",
        }

    html = load_filing_html(filing.local_path)
    full_text = filing_html_to_text(html)
    sections = extract_key_sections(full_text)

    return {
        "form": filing.form,
        "filing_date": filing.filing_date,
        "filing_url": filing.filing_url,
        "local_path": filing.local_path,
        "business": sections.get("business", ""),
        "risk_factors": sections.get("risk_factors", ""),
        "mdna": sections.get("mdna", ""),
        "full_text": sections.get("full_text", ""),
    }


def choose_section_text(sections: dict, *keys: str, min_chars: int = 0) -> str:
    fallback_text = ""

    for key in keys:
        value = _normalize_text(sections.get(key) or "")
        if not value:
            continue

        if len(value) >= min_chars or key == "full_text":
            return value

        if not fallback_text:
            fallback_text = value

    return fallback_text


def combine_section_texts(sections: dict, *keys: str, min_chars: int = 0) -> str:
    parts = []
    seen = set()

    for key in keys:
        value = _normalize_text(sections.get(key) or "")
        if not value:
            continue
        if len(value) < min_chars and key != "full_text":
            continue
        if value in seen:
            continue

        parts.append(value)
        seen.add(value)

    return " ".join(parts).strip()


def extract_latest_annual_sections(cik: str) -> dict:
    return extract_latest_filing_sections(
        cik,
        preferred_forms=("10-K", "20-F", "40-F", "10-Q", "6-K", "8-K"),
    )


def extract_latest_10k_sections(cik: str) -> dict:
    return extract_latest_annual_sections(cik)

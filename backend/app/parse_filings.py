"""Turn raw filing HTML into clean text and carve out the key sections.

This is the messiest, most interesting module: SEC filings are giant, sloppy
HTML documents with no consistent structure. There's no API for "give me the
Risk Factors section", so we:

  1. Strip HTML down to plain text (`filing_html_to_text`).
  2. Use regex "anchors" to locate the start of a section (e.g. "Item 1A. Risk
     Factors") and the start of the *next* section as the end boundary
     (`_find_section`), with heuristics to skip the table-of-contents and prefer
     a substantive (long enough) chunk over a stub.
  3. Expose the three sections analysts care about — Business, Risk Factors, and
     MD&A (Management's Discussion & Analysis) — plus the full text.

Because forms differ (10-K vs the foreign-issuer 20-F), each section has several
alternative start/end patterns. Pure regex/heuristics, no ML — deliberately so.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable

from sqlalchemy import select

from .config import resolve_storage_path
from .db import SessionLocal
from .models import Filing


# Section-extraction prefers annual reports (richest disclosure) then interims.
ANNUAL_FORMS = ("20-F", "10-K", "40-F")
INTERIM_FORMS = ("10-Q", "6-K", "8-K")
DEFAULT_PREFERRED_FORMS = ANNUAL_FORMS + INTERIM_FORMS


def load_filing_html(local_path: str | None) -> str:
    """Read a cached filing's HTML off disk; return "" if missing/unreadable."""
    if not local_path:
        return ""

    path = resolve_storage_path(local_path)
    if not path.exists():
        return ""

    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return ""


def filing_html_to_text(html: str) -> str:
    """Convert filing HTML to readable plain text using regex (no parser lib).

    Steps: drop script/style/head blocks entirely, convert block-level closing
    tags into newlines (to preserve paragraph structure), strip all remaining
    tags, decode a handful of common HTML entities, then collapse whitespace.
    `(?is)`/`(?i)` are inline regex flags: i=ignore-case, s=dotall (so `.`
    matches newlines too).
    """
    if not html:
        return ""

    text = html
    # Remove non-content blocks wholesale (their inner text is noise).
    text = re.sub(r"(?is)<script.*?>.*?</script>", " ", text)
    text = re.sub(r"(?is)<style.*?>.*?</style>", " ", text)
    text = re.sub(r"(?is)<head.*?>.*?</head>", " ", text)

    # Turn block boundaries into newlines so words don't get glued together.
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</p>", "\n", text)
    text = re.sub(r"(?i)</div>", "\n", text)
    text = re.sub(r"(?i)</tr>", "\n", text)
    text = re.sub(r"(?i)</li>", "\n", text)

    # Strip every remaining tag, leaving just the text content.
    text = re.sub(r"(?is)<[^>]+>", " ", text)

    # Decode the entities that actually show up in filings (smart quotes, dashes).
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

    # Tidy whitespace: collapse runs of spaces/tabs, and multiple blank lines.
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n\n", text)

    return text.strip()


def _normalize_text(text: str) -> str:
    """Collapse all whitespace (incl. newlines) to single spaces."""
    if not text:
        return ""
    return re.sub(r"\s+", " ", text).strip()


def _looks_like_table_of_contents(text: str) -> bool:
    """Heuristic: a chunk packed with several 'Item N' references near its start
    is almost certainly the table of contents, not the real section body."""
    preview = (text or "")[:800].lower()
    item_hits = re.findall(r"\bitem\s*\d+[a-z]?\b", preview)
    return len(item_hits) >= 3


def _extract_section_candidate(
    text: str,
    start_index: int,
    end_patterns: Iterable[str],
    *,
    max_chars: int,
    min_end_search_offset: int = 100,
) -> str:
    """Given a section start position, slice out the text up to the nearest
    end-pattern (the start of the following section).

    We look at a window of up to `max_chars` after the start, then find the
    earliest match of any end pattern. `min_end_search_offset` skips the first
    ~100 chars so the section *heading itself* (which may resemble an end
    pattern) doesn't immediately terminate the match.
    """
    search_region = text[start_index : start_index + max_chars]
    if not search_region:
        return ""

    end_index_relative = None
    search_offset = min(min_end_search_offset, len(search_region))

    # Find the closest end boundary across all candidate end patterns.
    for pattern in end_patterns:
        match = re.search(pattern, search_region[search_offset:], flags=re.IGNORECASE)
        if match:
            candidate = search_offset + match.start()
            if end_index_relative is None or candidate < end_index_relative:
                end_index_relative = candidate

    # No end found -> take the whole window; else cut at the boundary.
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
    """Locate one logical section and return its best text candidate.

    A section heading can appear several times in a filing (in the TOC, as a
    page header, and at the real section). So for each start pattern we gather
    *all* occurrences, extract a candidate body at each, throw out TOC-looking
    ones, and then pick the "best" — preferring candidates long enough to be the
    real thing (>= min_words), and among those the longest/latest one. If none
    clear the word bar, we keep the candidates as fallbacks and try the next
    pattern before settling.
    """
    if not text:
        return ""

    fallback_candidates = []

    for pattern in start_patterns:
        matches = list(re.finditer(pattern, text, flags=re.IGNORECASE))
        if not matches:
            continue

        candidates = []
        seen_starts = []

        for match in sorted(matches, key=lambda item: item.start()):
            start_index = match.start()

            # Skip near-duplicate start positions (same heading wrapped in tags).
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
            if _looks_like_table_of_contents(section):
                continue  # this hit was the TOC, not the body

            candidates.append(
                {
                    "start_index": start_index,
                    "text": section,
                    "word_count": len(section.split()),
                }
            )
            seen_starts.append(start_index)

        if not candidates:
            continue

        # A "substantive" candidate has enough words to be the real section.
        substantive_candidates = [
            candidate for candidate in candidates
            if candidate["word_count"] >= min_words
        ]

        ranked_candidates = substantive_candidates or candidates
        # Tie-break: most words, then latest position (real body sits after TOC).
        best_candidate = max(
            ranked_candidates,
            key=lambda candidate: (candidate["word_count"], candidate["start_index"]),
        )

        if substantive_candidates:
            return best_candidate["text"]  # confident match -> done

        # Otherwise remember these and let a later start pattern try to beat them.
        fallback_candidates.extend(candidates)

    if not fallback_candidates:
        return ""

    # No pattern produced a substantive hit; return the best short fallback.
    best_fallback = max(
        fallback_candidates,
        key=lambda candidate: (candidate["word_count"], candidate["start_index"]),
    )
    return best_fallback["text"]


# Each _extract_* below just supplies the start/end regex anchors for one
# section. Multiple alternatives cover 10-K phrasing AND 20-F (foreign-issuer)
# phrasing — e.g. a 10-K has "Item 1. Business" while a 20-F has "Item 4.
# Information on the Company". End patterns are the headings that come *next*.
def _extract_business(text: str) -> str:
    """Extract the Business section (what the company actually does)."""
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
    """Extract the Risk Factors section (the company's own risk disclosures)."""
    start_patterns = [
        r"\bitem\s*1a[\.\-:\s]+risk factors\b",
        r"\bitem\s*3d[\.\-:\s]+risk factors\b",
        r"\brisk factors\b",
        r"\bprincipal risks\b",
        r"\bkey risks\b",
    ]
    end_patterns = [
        r"\bitem\s*1b[\.\-:\s]+unresolved staff comments\b",
        r"\bitem\s*1c[\.\-:\s]+cybersecurity\b",
        r"\bitem\s*2[\.\-:\s]+properties\b",
        r"\bitem\s*3[\.\-:\s]+legal proceedings\b",
        r"\bitem\s*4[\.\-:\s]+mine safety disclosures\b",
        r"\bitem\s*4[\.\-:\s]+information on the company\b",
        r"\bitem\s*4a\b",
    ]
    return _find_section(text, start_patterns, end_patterns)


def _extract_mdna(text: str) -> str:
    """Extract MD&A — Management's Discussion & Analysis (the narrative on
    results, trends, and outlook)."""
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
    """Run all three section extractors over one filing's text at once."""
    business = _extract_business(text)
    risk_factors = _extract_risk_factors(text)
    mdna = _extract_mdna(text)

    return {
        "business": business,
        "risk_factors": risk_factors,
        "mdna": mdna,
        "full_text": text or "",  # keep the whole text as a last-resort fallback
    }


def _pick_best_filing(cik: str, preferred_forms: Iterable[str]) -> Filing | None:
    """Choose the single most relevant filing to analyze for a company.

    Ranks by (1) form preference order — earlier in `preferred_forms` wins, so
    annual reports beat interims — then (2) newest filing date, then (3)
    accession number as a deterministic tie-break.
    """
    preferred_forms = tuple(preferred_forms)

    with SessionLocal() as session:
        stmt = select(Filing).where(
            Filing.cik == cik,
            Filing.form.in_(preferred_forms),
        )
        filings = session.execute(stmt).scalars().all()

    if not filings:
        return None

    # Map each form to its position so we can sort by preference.
    form_rank = {form: idx for idx, form in enumerate(preferred_forms)}

    def sort_key(filing: Filing):
        return (
            form_rank.get(filing.form, 999),  # preferred form first
            # Negate the YYYYMMDD int so that, ascending sort -> newest first.
            -int(filing.filing_date.replace("-", "")) if filing.filing_date else -1,
            filing.accession_no or "",
        )

    filings.sort(key=sort_key)
    return filings[0]


def extract_latest_filing_sections(
    cik: str,
    preferred_forms: Iterable[str] = DEFAULT_PREFERRED_FORMS,
) -> dict:
    """Pick the best filing, load+parse it, and return its sections + metadata.

    This is the main entry point most callers use to get analyzable text for a
    company. Returns empty strings (not None) for sections if nothing is found.
    """
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
    """Pick the FIRST section (in priority order `keys`) that's long enough.

    Used to feed scorers with the best available text, e.g.
    choose_section_text(sections, "risk_factors", "mdna", "business",
    "full_text", min_chars=500) means "use risk_factors if it has >=500 chars,
    else fall back to mdna, then business, then the whole document". The first
    non-empty but too-short value is remembered as a last resort.
    """
    fallback_text = ""

    for key in keys:
        value = _normalize_text(sections.get(key) or "")
        if not value:
            continue

        # full_text always qualifies (it's the ultimate fallback).
        if len(value) >= min_chars or key == "full_text":
            return value

        if not fallback_text:
            fallback_text = value

    return fallback_text


def combine_section_texts(sections: dict, *keys: str, min_chars: int = 0) -> str:
    """Like choose_section_text, but CONCATENATES all qualifying sections.

    De-dupes identical chunks. Used by the geopolitics scorer, which wants as
    much exposure-relevant filing text as possible in one blob.
    """
    parts = []
    seen = set()

    for key in keys:
        value = _normalize_text(sections.get(key) or "")
        if not value:
            continue
        if len(value) < min_chars and key != "full_text":
            continue
        if value in seen:
            continue  # avoid duplicating the same text twice

        parts.append(value)
        seen.add(value)

    return " ".join(parts).strip()


def extract_latest_annual_sections(cik: str) -> dict:
    """Convenience wrapper: prefer annual reports (10-K/20-F/40-F) for sections."""
    return extract_latest_filing_sections(
        cik,
        preferred_forms=("10-K", "20-F", "40-F", "10-Q", "6-K", "8-K"),
    )

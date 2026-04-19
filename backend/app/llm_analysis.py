import json
import os

from groq import Groq
from pydantic import BaseModel


class LLMAnalysis(BaseModel):
    enhanced_summary: str
    investment_thesis: str
    key_risks: list[str]
    key_strengths: list[str]
    score_commentary: str
    red_flags: list[str]


_SYSTEM_PROMPT = """You are an expert financial analyst specializing in SEC filing analysis for equity research.

You will receive:
1. Rule-based scores (0–100) computed by keyword analysis of SEC filings
2. Financial metrics extracted from XBRL data
3. Excerpts from the actual SEC filing text (Risk Factors, Business description, MD&A)
4. Evidence sentences that triggered keyword risk scores
5. Year-over-year change data

Respond with a JSON object containing exactly these six keys:

{
  "enhanced_summary": "3–4 sentences synthesizing the quantitative scores with the qualitative filing language. Be specific about what drives each score — don't just restate the numbers.",
  "investment_thesis": "2–3 sentences capturing the core opportunity and the primary risk. Portfolio-manager quality — someone should be able to use this in a brief.",
  "key_risks": ["3–5 specific, material risks grounded in actual filing language. Name each risk and briefly explain why it is material to this specific company."],
  "key_strengths": ["3–5 specific strengths grounded in actual filing language or financial metrics. Be concrete, not generic."],
  "score_commentary": "1–2 sentences on whether the keyword scores appear to accurately reflect the true risk/quality profile, or if they over- or understate it based on your reading of the filing excerpts.",
  "red_flags": ["0–3 notable concerns not fully captured by the standard scores — empty array if none"]
}

Rules:
- Output ONLY valid JSON with no markdown fences, no preamble, no explanation outside the JSON
- Cite actual language from the filings when possible
- Avoid generic boilerplate that could apply to any company
- If filing text is sparse or unavailable, note that limitation explicitly"""


def _truncate(text: str, max_chars: int) -> str:
    if not text or len(text) <= max_chars:
        return text or ""
    return text[:max_chars] + "..."


def _build_evidence_block(evidence: dict) -> str:
    lines = []
    for category, sentences in evidence.items():
        if sentences:
            lines.append(f"{category.upper()}:")
            for s in sentences[:2]:
                lines.append(f"  - {s}")
    return "\n".join(lines) or "No evidence sentences extracted."


def generate_llm_analysis(
    company_name: str,
    ticker: str | None,
    opinion_data: dict,
    sections: dict,
) -> LLMAnalysis | None:
    """Call Groq (Llama 3.3 70B) to produce a richer narrative analysis.

    Returns None if GROQ_API_KEY is not set or if the API call fails.
    """
    api_key = os.getenv("GROQ_API_KEY", "")
    if not api_key:
        return None

    client = Groq(api_key=api_key)

    scores = opinion_data.get("scores", {})
    details = opinion_data.get("details", {})
    metrics = details.get("financial", {}).get("metrics_used", {})
    evidence = details.get("risk", {}).get("evidence_sentences", {})
    change_details = details.get("change_detection", {})

    score_changes_str = str(change_details.get("score_changes", "No change data."))[:600]

    user_message = f"""COMPANY: {company_name} ({ticker or "N/A"})

RULE-BASED SCORES (0–100):
- Financial Quality: {scores.get("financial", "N/A")}
- Risk Score: {scores.get("risk", "N/A")}  (higher = more risk language in filing)
- Business Model: {scores.get("business_model", "N/A")}
- Moat / Competitive Position: {scores.get("moat", "N/A")}
- Geopolitical Impact: {scores.get("geopolitical", "N/A")}  (higher = more exposure)
- Overall Score: {opinion_data.get("overall_score", "N/A")} / 100

KEY FINANCIAL METRICS:
- Revenue: {metrics.get("revenue", "N/A")}
- Net Income: {metrics.get("net_income", "N/A")}
- Operating Margin: {metrics.get("operating_margin", "N/A")}
- Operating Cash Flow: {metrics.get("operating_cash_flow", "N/A")}
- Total Debt: {metrics.get("total_debt", "N/A")}

RISK EVIDENCE SENTENCES (from filing):
{_build_evidence_block(evidence)}

YEAR-OVER-YEAR SCORE CHANGES:
{score_changes_str}

RISK FACTORS EXCERPT:
{_truncate(sections.get("risk_factors", ""), 3000)}

BUSINESS DESCRIPTION EXCERPT:
{_truncate(sections.get("business", ""), 2000)}

MD&A EXCERPT:
{_truncate(sections.get("mdna", ""), 2000)}"""

    try:
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": user_message},
            ],
            temperature=0.2,
        )

        raw = response.choices[0].message.content
        data = json.loads(raw)
        return LLMAnalysis(**data)

    except Exception as e:
        print(f"\n[LLM] Analysis unavailable: {e}")
        return None

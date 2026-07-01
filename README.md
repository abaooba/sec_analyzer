# SEC Analyzer

[![CI](https://github.com/abaooba/sec_analyzer/actions/workflows/ci.yml/badge.svg)](https://github.com/abaooba/sec_analyzer/actions/workflows/ci.yml)

Type a company name and get an explainable, analyst-grade read on it — built from
**real SEC filings and financials**, scored across **five dimensions**, with a
thin LLM layer writing the narrative *on top* of the numbers.

The design is deliberately **"AI-last"**: regex + weighted keyword counts +
ratio math do the scoring (so every number traces back to evidence — sentences,
facts, ratios), and the language model only *synthesizes* a narrative from those
explainable scores. It never invents the scores.

Everything runs on **free, public data** — no paid vendors.

> This README is the quick start. [`LEARNINGS.md`](./LEARNINGS.md) is the deep
> reference (architecture, every data-source gotcha, and the iteration log).

---

## How it works

```
"Apple" ─► company_lookup ─► CIK ─┬─► ingest        (filing HTML → cache + DB)
                                  └─► fundamentals  (XBRL facts → company_facts)
                                          │
                                          ▼
                                      opinion.py  (orchestrator)
        ┌──────────┬──────────────┬───────┴───────┬──────────────┐
   financials     risk      business_model      moat        geopolitics
    (numbers)  (keywords)     (keywords)      (keywords)   (news + filing)
        └──────────┴──────────────┬───────────────┴──────────────┘
                          weighted blend → overall_score (0–100)
                                          ▼
                          llm_analysis.py → AI narrative (optional)
                                          ▼
                          CLI report (main.py)  /  JSON API (api.py)
```

The five scores blend into one 0–100 number (higher = better). Risk and
geopolitics are **inverted**, because more of them is worse:

```
overall = financial·0.25 + (100−risk)·0.20 + business_model·0.20
        + moat·0.15 + (100−geopolitics)·0.20
```

| Dimension | Signal |
|---|---|
| **Financial** | Margins, ROE, free cash flow, leverage from XBRL facts |
| **Risk** | Weighted risk-language keywords in the filing's Risk Factors |
| **Business model** | Durability / quality keywords (positive and negative) |
| **Moat** | Competitive-advantage keywords (brand, switching costs, scale, ecosystem) |
| **Geopolitics** | Live news events × the filing's stated exposure |

**Beyond the blended score**, every opinion also carries four *signature signals*
(additive — they don't change the 0–100 blend):

| Signal | What it tells you |
|---|---|
| **Confidence** | How much real data backs the scores (filing sections found, XBRL metrics, YoY data, news) — high / moderate / low |
| **Forensic flags** | Accounting/disclosure red flags (going-concern, restatement, material weakness, impairment, …) surfaced explicitly, with evidence |
| **Score trajectory** | Risk / business-model / moat *text* scores across the last few annual filings — which way the disclosure profile is trending |
| **Contradictions** | Internal tensions worth a second look (e.g. a strong headline score undercut by a forensic flag that sits outside the blend) |

---

## Quick start

Requires **Python 3.13+**.

```bash
git clone https://github.com/abaooba/sec_analyzer.git
cd sec_analyzer

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Configure. The SEC REQUIRES a descriptive User-Agent (name + email) or it
# returns HTTP 403 — this is their fair-access policy, not optional.
cp .env.example .env
#   edit .env:  SEC_USER_AGENT="Your Name your.email@example.com"
#   optional:   GROQ_API_KEY=...   (for the AI narrative; omit to run rule-only)
```

### Run the CLI

```bash
python -m backend.main
# → prompts for a company name, prints a formatted report
```

### Run the API

```bash
uvicorn backend.api:app --reload

curl -X POST localhost:8000/analyze \
  -H 'content-type: application/json' \
  -d '{"company_name": "Apple", "ticker": "AAPL"}'
```

`ticker` is optional. The response is the full opinion JSON: `overall_score`,
per-dimension `scores`, `strengths`, `weaknesses`, `summary`, the evidence-rich
`details` block, `llm_analysis` (or `null` when no `GROQ_API_KEY` is set), and the
four signature signals above (`confidence`, `forensic`, `score_trajectory`,
`contradictions`).

The database (SQLite) and the filing cache are created automatically on first run.

### Factor exposure & attribution

A second, standalone endpoint answers a different question — *is a return alpha,
or just factor beta?* It decomposes a portfolio (or single stock/ETF) against the
**Fama-French 5-factor + Momentum** model: static + rolling factor betas, alpha
(with significance), and a return-attribution waterfall.

```bash
curl -X POST localhost:8000/factor-attribution \
  -H 'content-type: application/json' \
  -d '{"holdings": [{"ticker": "AAPL", "weight": 0.6}, {"ticker": "MSFT", "weight": 0.4}]}'
# or a single name:  -d '{"ticker": "SPY"}'
```

Prices come from yfinance and the factors from the Ken French Data Library (no
keys). The response shape, a sample payload, and a frontend handoff guide live in
[`docs/factor-attribution.md`](./docs/factor-attribution.md). The heavy quant
stack (statsmodels / pandas / yfinance) is imported lazily, so it only loads when
this endpoint is hit — `/analyze` and app startup are unaffected.

### Cross-sectional fundamental screen

A third, standalone endpoint ranks a **universe of tickers** against each other on
five classic quant metrics — **Piotroski F-Score** (9 binary tests), **Altman
Z-Score**, **Sloan accruals**, **ROIC**, and **FCF yield** — then flags financial
**distress** (low Z) and **earnings-quality risk** (high accruals) and returns a
ranked, color-coded table plus a **value-vs-quality** scatter.

```bash
curl -X POST localhost:8000/screen \
  -H 'content-type: application/json' \
  -d '{"tickers": ["AAPL", "MSFT", "NVDA", "GOOGL", "KO", "F"]}'
```

Or from the terminal (color table + ASCII scatter, and a PNG when `matplotlib` is
installed):

```bash
python -m backend.screen AAPL MSFT NVDA GOOGL KO F
```

Metrics are computed from the same SEC XBRL facts, over a clean year-over-year
annual history (keyed by period-end, restatement-aware). The Altman model adapts to
the data — classic (with a market cap from yfinance) or book-value Z″ without one.
The response shape, a sample payload, and a frontend handoff guide live in
[`docs/screen.md`](./docs/screen.md).

---

## Tests

```bash
pip install -r requirements-dev.txt
pytest
```

The suite is fully offline — SEC/Groq are monkeypatched and the database is
in-memory — so it needs no network and no secrets. CI runs it on every push.

---

## Data sources (all free)

| Source | What it provides |
|---|---|
| SEC EDGAR `company_tickers.json` | ticker → CIK mapping |
| SEC `submissions` API | a company's filing history |
| SEC `companyfacts` XBRL API | structured financials |
| SEC `Archives` | the raw filing HTML |
| Google News RSS | live headlines (no API key) |
| Groq (Llama 3.3 70B) | the *optional* narrative layer |
| Ken French Data Library | daily Fama-French 5 + Momentum factor returns (factor attribution) |
| yfinance | daily adjusted prices for the factor-attribution portfolio |

---

## Security

Never commit a real `.env` — it is gitignored, and `.env.example` holds only
placeholders. API keys belong in your local `.env` (or the environment), never in
source. If a key is ever exposed, rotate it provider-side.

---

## Layout

```
backend/app/        config, db/models, SEC/news clients, ingest, parsing,
                    scoring/ (the five scorers), opinion.py (orchestrator),
                    llm_analysis.py (the AI-last layer)
backend/app/factors/  factor exposure & attribution (Fama-French regressions):
                    factor_data, prices, regression, attribution, service
backend/app/screening/  cross-sectional screen (Piotroski / Altman / accruals /
                    ROIC / FCF yield): metrics, ranking, render, market_data, service
backend/app/fundamentals_history.py  clean year-over-year annual XBRL snapshots
backend/api.py      FastAPI /analyze + /factor-attribution + /screen endpoints
backend/main.py     interactive CLI    ·    backend/screen.py  screen CLI
backend/tests/      pytest suite (offline, in-memory DB)
docs/               frontend handoff contracts (/analyze + /factor-attribution + /screen)
LEARNINGS.md        deep reference + iteration log
```

# SEC Analyzer — What This Project Is & Everything It Taught Me

A from-scratch tool that takes a company name, pulls its real SEC filings and
financial data, scores it across five dimensions, detects what changed
year-over-year, mixes in live news, and then has an LLM write an analyst-grade
opinion on top. CLI **and** web API.

This document is the "field notes" version: every resource, library, concept,
and clever trick that went into building it by hand.

---

## 1. The 10,000-foot view

```
                 ┌─────────────────────────────────────────────┐
   "Apple"  ───► │ company_lookup  → CIK (SEC's company id)     │
                 └─────────────────────────────────────────────┘
                                   │
        ┌──────────────────────────┴──────────────────────────┐
        ▼                                                      ▼
 ingest.py                                          fundamentals.py
 (download filing HTML →                            (download XBRL facts →
  cache on disk + DB rows)                           company_facts table)
        │                                                      │
        └──────────────────────────┬──────────────────────────┘
                                   ▼
                              opinion.py  (the orchestrator)
                                   │
   ┌───────────────┬───────────────┼───────────────┬───────────────┐
   ▼               ▼               ▼               ▼               ▼
financials     risk           business_model     moat          geopolitics
(numbers)    (keywords)        (keywords)      (keywords)    (news + filing)
   │               │               │               │               │
   └───────────────┴───────────────┼───────────────┴───────────────┘
                                   ▼
                  weighted blend → overall_score (0–100)
                  + strengths / weaknesses / summary
                  + change_detection (year-over-year diff)
                                   ▼
                  llm_analysis.py → AI narrative (JSON)
                                   ▼
                  CLI report (main.py)  /  JSON API (api.py)
```

The whole thing is **deliberately "old school"**: regex and weighted keyword
counts do the heavy lifting, not machine learning. The LLM is the *last* layer,
not the engine. That makes every score explainable.

---

## 2. The data sources (the genuinely cool part)

Everything here is **free and public** — no paid data vendor.

| Source | What it gives | How it's accessed |
|---|---|---|
| **SEC EDGAR `company_tickers.json`** | Every ticker → CIK mapping | One JSON download, matched in Python |
| **SEC `submissions/CIK##########.json`** | A company's filing history | `data.sec.gov` REST |
| **SEC `companyfacts` XBRL API** | Structured financials (revenue, assets, …) | `data.sec.gov/api/xbrl` |
| **SEC `Archives/edgar/data/...`** | The raw filing HTML documents | `www.sec.gov/Archives` |
| **Google News RSS** | Live news headlines, no API key | `news.google.com/rss/search?q=...` |

### Things I learned about the SEC API specifically
- **CIK = Central Index Key**, the SEC's permanent id for a filer. It must be
  **zero-padded to 10 digits** for the JSON APIs (`"320193"` → `"0000320193"`)…
- …**but** in the archive document URL the CIK has its **leading zeros stripped**
  and the accession number has its **dashes removed**. Two different conventions
  for the same ids — a classic real-world API gotcha.
- The SEC **requires a descriptive `User-Agent`** header (name + email) or it
  returns `403`. This is their fair-access policy, not optional.
- The submissions API returns filings as **parallel arrays** (column-oriented):
  `form[i]`, `accessionNumber[i]`, `filingDate[i]` all line up by index. You
  `zip()` them back into rows.
- **XBRL** (eXtensible Business Reporting Language) is the standardized
  financial-data format. One "fact" = a tagged number for a period
  (`tag=Revenues, unit=USD, fy=2023, val=...`). The same fact gets repeated
  across many filings, so **de-duplication on ingest is essential**.
- **us-gaap vs ifrs-full**: US filers tag under `us-gaap`, foreign filers under
  `ifrs-full`, and they use *different names for the same concept*
  (`Revenues` vs `Revenue` vs `RevenueFromContractsWithCustomers`). Hence the
  whitelist-of-synonyms approach in `fundamentals.py` and `metrics.py`.

### Filing form types (a mini accounting glossary I picked up)
| Form | Meaning |
|---|---|
| **10-K** | US annual report (the big one) |
| **10-Q** | US quarterly report |
| **8-K** | US "material event" report (ad hoc) |
| **20-F** | Annual report for **foreign** private issuers |
| **6-K** | Interim report for foreign issuers |
| **40-F** | Annual report for **Canadian** issuers |

---

## 3. Libraries used (and *why* each one)

| Library | Role in this project | Why it / what I learned |
|---|---|---|
| **httpx** | All HTTP calls (SEC, news) | Modern `requests` successor; clean context-manager clients, timeouts, redirect following, `raise_for_status()` |
| **SQLAlchemy 2.0** | ORM / database | Typed `Mapped[...]` + `mapped_column` style, `select()` core queries, `sessionmaker`, `Base.metadata.create_all()` |
| **pydantic v2** | Settings + request/response schemas + LLM validation | `BaseModel` as a typed config bag, automatic type coercion, FastAPI request bodies, validating LLM JSON |
| **FastAPI** | The web API | Decorator routes, automatic JSON (de)serialization from pydantic models, dependency-free request validation |
| **uvicorn** | ASGI server to run FastAPI | `uvicorn backend.api:app --reload` |
| **CORS middleware** | Let a browser frontend call the API | Cross-Origin Resource Sharing basics |
| **python-dotenv** | Load secrets from `.env` | Keeps API keys out of source control |
| **feedparser** | Parse RSS/Atom feeds | Turns Google News RSS XML into structured entries |
| **trafilatura** | Extract clean article text from a URL | Boilerplate removal (strips nav/ads), main-content extraction |
| **groq** | LLM inference client | OpenAI-compatible chat API, **JSON mode**, very fast Llama hosting |
| **(stdlib) re** | The actual workhorse | Section extraction + all keyword scoring is regex |
| **(stdlib) pathlib** | Path handling | `Path`, `.resolve()`, `parents[]`, `.mkdir()`, `.write_text()` |
| **(stdlib) urllib.parse** | `quote_plus` for building search URLs | URL-encoding query strings |

---

## 4. Concepts & techniques I actually learned by doing this

### Software / Python
- **Layered architecture**: `config → db/models → clients → ingest → parse →
  scoring → opinion → entry points`. Each layer only imports "downward." Two
  entry points (CLI + API) share one pipeline.
- **The `settings` singleton pattern**: one pydantic object built once at import,
  imported everywhere, so configuration lives in exactly one place.
- **Path-resolution that's independent of the working directory** — resolving
  relative to the repo root so the app behaves identically whether launched from
  the repo, the backend folder, or uvicorn.
- **`if __package__ in {None, ""}: sys.path.insert(...)`** — the shim that lets a
  file run both as `python -m backend.main` *and* as a loose script.
- **Upsert pattern**: `session.get(...)` → update if found, insert if not.
- **De-duplication via a uniqueness tuple** (XBRL facts) and via a **set** for
  O(1) membership tests (new-sentence detection).
- **`try/finally` for cleanup**: cached HTML is always deleted, even on error.
- **Graceful degradation**: no LLM key → return `None` and fall back to the
  rule-based output; news fetch fails → score on filing exposure alone. The app
  never hard-crashes on an optional dependency.
- **Client-side rate limiting**: a process-wide throttle (last-call timestamp +
  a `threading.Lock`) spaces SEC requests to honor an API's fair-access policy —
  a single shared limiter rather than per-object, so a tight download loop can't
  burst past the limit.
- **Bounded, best-effort enrichment**: full article-body fetching is capped to a
  few articles and silently skips failures, so an expensive/flaky network step
  improves quality without ever blocking the result.
- **Parallel-array → row** transformation with `zip()`.

### Regex (this project is a regex bootcamp)
- Inline flags: `(?i)` ignore-case, `(?is)` ignore-case + dotall (`.` matches
  newlines), `(?s)` dotall.
- **Word boundaries** `\b` so `\binflation\b` doesn't match inside other words.
- **Lookbehind** `(?<=[.!?])\s+` to split sentences *after* punctuation without
  consuming it.
- Non-greedy matching `.*?` to strip `<script>…</script>` blocks.
- HTML → text **without a parser**: drop script/style/head, convert block-closing
  tags to newlines, strip remaining tags, decode entities, collapse whitespace.

### Information retrieval / NLP-lite
- **Anchor-based section extraction**: find a heading ("Item 1A. Risk Factors"),
  treat the *next* heading as the end boundary, and slice between them. With
  heuristics to (a) skip the table of contents, and (b) prefer a chunk long
  enough to be the real section over a stub.
- **Count "softening"** (`0 / 1-2 / 3-5 / 6+ → 0/1/2/3`) so a term repeated 40
  times doesn't dominate — we care about *emphasis*, not raw frequency.
- **Weighted, capped scoring**: per-category caps + category weights + a total
  cap, so no single signal can run away with the score.
- **Evidence extraction**: pulling the actual sentences that triggered a score,
  which both explains the number to a human and grounds the LLM.
- **Set-difference change detection**: this year's sentences minus last year's =
  newly added language (often the most interesting part of a filing).

### Finance (picked up along the way)
- **Operating margin** = operating income / revenue.
- **ROE** (return on equity) ≈ net income / equity.
- **Free cash flow** ≈ operating cash flow − capex.
- **Leverage**: debt/equity (preferred) or debt/assets (fallback).
- **Balance-sheet strength**: liabilities / assets, plus equity sign.
- **"Moat"** = durable competitive advantage (brand, switching costs, IP, scale,
  network/ecosystem lock-in) — Buffett's term, operationalized here as keyword
  categories.

### LLM / AI engineering
- **System prompt that pins an exact output schema** (the six required JSON keys).
- **JSON mode** (`response_format={"type": "json_object"}`) to force valid JSON.
- **pydantic validation of the model's response** so a malformed reply is caught.
- **Low temperature (0.2)** for grounded, repeatable output.
- **Context budgeting**: truncating filing excerpts to fit the prompt window.
- **The LLM as the *last* layer**: deterministic scores first (explainable),
  narrative synthesis second. The AI is asked to *critique* the keyword scores
  ("do they over/understate the real risk?"), not produce them.

---

## 5. File-by-file map

| File | Responsibility |
|---|---|
| `backend/app/config.py` | Settings singleton, env loading, repo-relative path resolution |
| `backend/app/db.py` | SQLAlchemy engine + `SessionLocal` + `init_db()` |
| `backend/app/models.py` | ORM tables: `Company`, `Filing`, `CompanyFact` |
| `backend/app/sec_client.py` | HTTP wrapper for the SEC EDGAR APIs + a process-wide rate-limit throttle |
| `backend/app/company_lookup.py` | Name/ticker → CIK matching |
| `backend/app/ingest.py` | Download filing HTML → cache + DB; cleanup |
| `backend/app/fundamentals.py` | Download XBRL facts → `company_facts` (de-duped) |
| `backend/app/metrics.py` | Latest-fact selection, ratio math, display formatting |
| `backend/app/parse_filings.py` | HTML→text + regex section extraction (Business / Risk / MD&A) |
| `backend/app/scoring/financials.py` | Number-based financial quality score |
| `backend/app/scoring/risk.py` | Keyword risk score + evidence sentences |
| `backend/app/scoring/business_model.py` | Two-sided (positive/negative) model-quality score |
| `backend/app/scoring/moat.py` | Competitive-moat keyword score |
| `backend/app/scoring/geopolitics.py` | News-event × filing-exposure fusion score (enriches top articles with full body text) |
| `backend/app/rss_client.py` | Fetch + parse an RSS feed |
| `backend/app/rss_ingest.py` | Build Google News queries, normalize + dedupe articles |
| `backend/app/article_extractor.py` | Full-article text extraction via trafilatura — used by the geopolitics scorer |
| `backend/app/change_detection.py` | Year-over-year filing comparison |
| `backend/app/opinion.py` | **Orchestrator** — runs everything, blends the final score |
| `backend/app/llm_analysis.py` | LLM narrative layer (Groq / Llama 3.3 70B) |
| `backend/api.py` | FastAPI `/analyze` endpoint |
| `backend/main.py` | Interactive CLI with a formatted terminal report |

---

## 6. How the final score is built

```
overall =  financial        * 0.25
        + (100 − risk)       * 0.20      # inverted: more risk language = worse
        +  business_model    * 0.20
        +  moat              * 0.15
        + (100 − geopolitics)* 0.20      # inverted: more exposure = worse
```

Weights sum to 1.0; the result is clamped to 0–100. The two "bad" meters (risk,
geopolitics) are inverted so the final number always reads "higher = better."

---

## 7. Cleanup pass — what got connected back
A later pass removed the loose ends so nothing dangles:
- **`article_extractor.py` is now wired into the geopolitics scorer.** It fetches
  the real body text of the top few news articles (bounded by
  `FULL_TEXT_ARTICLE_LIMIT`, best-effort) so classification sees more than the
  headline. The result now reports `full_text_article_count`.
- **`max_requests_per_second` is now enforced.** `sec_client._throttle()` is a
  process-wide rate limiter (timestamp + lock) every SEC call passes through, so
  the ingest download loop stays under the SEC's fair-access limit.
- **The model label can no longer drift.** `LLM_MODEL` / `LLM_DISPLAY_NAME` live
  in `llm_analysis.py` as the single source of truth; the CLI imports the display
  name instead of hardcoding it (it used to wrongly print "Claude Opus 4.7").
- **Config is honest.** `llm_analysis` now reads `settings.groq_api_key` instead
  of `os.getenv` directly, and the dead `news_api_*` / `processed_data_dir`
  settings and the unused `extract_latest_10k_sections` alias were removed —
  every remaining `Settings` field now has a real consumer.

### Still open / future work
- `allow_origins=["*"]` and `verify=False` (TLS) are convenient but should be
  tightened for anything real.
- HTML parsing is pure regex — robust enough for SEC filings, but a parser like
  `selectolax`/`lxml` would be sturdier (the dependency is even installed).
- Keyword lists in `moat.py` lean toward semiconductor/equipment language,
  reflecting the filings this was first tuned against — generalizing them is
  future work.

---

## 8. The one-sentence takeaway
You can build a genuinely useful equity-research tool out of **free public data,
a pile of well-chosen regexes, a SQLite database, and a thin LLM layer** — and
keeping the AI *last* is what makes every number it reports explainable.

---

## 9. Iteration log (self-improvement loop)

This section is the running log. Each iteration: pick the single highest-priority
unfinished backlog item (T0→T5, security/test-debt first), ship one closed +
tested + committed unit, and append a dated entry here.

### 2026-06-24 — T0 SECURITY: stop tracking `.env`, fix `.gitignore`, add `.env.example`

**What changed**
- `git rm --cached backend/app/.env`. The file had been *re-staged* (`A` in
  `git status`) this session even though an earlier commit (`d470b87`) claimed to
  stop tracking it. Removed it from the index again; working-tree copy preserved
  (local real keys intact, byte-identical on disk).
- Rewrote `.gitignore`: split the broken `*.pyc.env` line into `*.pyc` + `.env`,
  added `**/.env` (the old `backend/.env` rule never matched the real path
  `backend/app/.env`), and `!.env.example` so the template stays trackable.
- Added `.env.example` with empty/placeholder values for exactly the **6** env
  vars `config.py` actually reads: `SEC_USER_AGENT`, `GROQ_API_KEY`,
  `DATABASE_URL`, `RAW_FILINGS_DIR`, `REQUEST_TIMEOUT`, `MAX_REQUESTS_PER_SECOND`.
  Dropped the dead `NEWS_API_*` / `PROCESSED_DATA_DIR` entries that still lingered
  in the on-disk `.env` (no code reads them — confirmed by grep).

**Why** — `.env` with live credentials was committed in `1e2124b` / `f417aa6`,
removed in `d470b87`, but those secret blobs remain reachable from `origin/main`
on a **PUBLIC** GitHub repo (`github.com/abaooba/sec_analyzer`). The `.gitignore`
was also broken, so the file kept getting re-added.

**🚨 REQUIRED — provider-side, NOT done by me (a real secret cannot be faked):**
- **Rotate the Groq key** (`gsk_…`) at https://console.groq.com/keys — revoke the
  leaked one, issue a new one, drop it in local `.env`.
- **Rotate the News API key** (`06ac…`, newsapi.org-style) in that provider's
  console — even though `config.py` no longer reads it, it is a live leaked
  credential that was pushed publicly.
- The leaked keys remain in **public git history**; rotation is what neutralizes
  them. A full history scrub (`git filter-repo` + force-push) is the optional
  deep-clean but is destructive and rewrites public history, so it is left to the
  user — not run autonomously (the loop forbids force-push / destructive git).

**Verification** — `git check-ignore -v` confirms `backend/app/.env` is ignored
(via `**/.env`) and `.env.example` is trackable; `.env` no longer appears in
`git status`; `from app.config import settings` still imports; `.env` content
intact on disk (explicit-path `load_dotenv` still loads the real Groq key).

**Discovered (not fixed — future work)** — bare `load_dotenv()` searches the CWD
upward, so it does **not** find `backend/app/.env` when the app is launched from
the repo root; the Groq key then silently fails to load and the LLM layer degrades
to rule-only. Latent config-robustness bug → candidate for **T2** (point
`load_dotenv` at an explicit repo-relative path, e.g. `BACKEND_DIR/"app/.env"`).

**Now unblocked / next iteration** — T0 code remediation is complete; only the
provider-side key rotation remains (on the user). Start **T1 SAFETY NET** next:
pytest suite (opinion.py blend formula, count-softening buckets, metrics.py
ratios, parse_filings.py section extraction with a saved filing fixture; mock
SEC/Groq), then ruff + mypy config + missing type hints, then GitHub Actions CI.
NOTE: this repo currently has **no test or lint tooling at all**, so T1 is the
prerequisite for every later tier — do it before any T2+ work.

### Backlog status (mirror of the /timebox brief — keep in sync)
- **T0 SECURITY** — code remediation ✅ (untrack `.env`, fix `.gitignore`, add
  `.env.example`; committed). Key rotation ⏳ **BLOCKED on user** (surfaced above).
- **T1 SAFETY NET** — ⬜ next up (pytest suite, ruff+mypy config + type hints, CI).
- **T2 ROBUSTNESS** — ⬜ (CORS scope, drop `verify=False`, logging, externalize
  scoring keywords/weights, LLM validation retry+fallback; also the `load_dotenv`
  path bug found above).
- **T3 CLEANUP** — ⬜ (prune unused deps, async-safe rate limiter, root README).
- **T4 SIGNATURE FEATURES** — ⬜ blocked until T0–T1 done (forensics scores,
  confidence, trajectory, backtesting).
- **T5 REACH FEATURES** — ⬜ (insider/institutional, peer-relative, contradiction
  detector, RAG Q&A, frontend, watchlist/alerts, PDF export).

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

### 2026-06-24 — T1 SAFETY NET (part 1): pytest suite

**What changed** — Added the test net, *purely additively* (new files only, no
edits to any existing module):
- `pyproject.toml` — `[tool.pytest.ini_options]` (`pythonpath=["."]`,
  `testpaths=["backend/tests"]`).
- `requirements-dev.txt` — pins `pytest`, `ruff`, `mypy` (installed into `.venv`).
- `backend/tests/conftest.py` — an isolated **in-memory SQLite** fixture
  (`StaticPool` so it survives multiple `SessionLocal()` calls) + monkeypatches
  that repoint `metrics`/`parse_filings` `SessionLocal` at it, so DB tests never
  touch the real `sec_analyzer.db`.
- `backend/tests/fixtures/sample_10k.html` — a synthetic 10-K (dense TOC +
  substantive Business / Risk / MD&A sections, each with a unique marker).
- `test_risk_scoring.py`, `test_metrics.py`, `test_parse_filings.py`,
  `test_opinion.py` — **53 tests, all green** covering the four brief areas:
  count-softening buckets + risk scoring; metrics formatters + the derived-ratio
  math (via seeded DB, incl. divide-by-zero/missing guards + latest-fact pick);
  HTML→text + section extraction on the fixture + TOC-skip + choose/combine;
  and the opinion **blend formula**.

**How the blend is tested (and how SEC/Groq are "mocked")** — instead of editing
`opinion.py` to extract a helper (which would have meant touching WIP — see below),
the blend is exercised through the *real* `build_full_opinion` with all five
scorers + `detect_filing_changes` + `generate_llm_analysis` monkeypatched to fixed
values. That keeps it offline (no SEC/Groq/DB) yet verifies the real `.25/.20/.20/
.15/.20` weighting, the risk & geopolitics inversion, the clamp, and the CIK
zero-padding — not a re-implementation.

**Why purely additive (important constraint)** — the working tree carries an
**806-line uncommitted diff** across 22 files: the "cleanup pass" documented in
§7 (docstrings + the throttle / article-extractor wiring). It is the user's
complete-but-uncommitted work; bundling it into a test commit (or committing it on
their behalf) was out of scope, so this iteration touched **zero** existing files
and committed only new ones. The diff is still uncommitted.

**Discovered** — the section extractor *balloons* a section when the TOC is too
sparse: a TOC-origin "Management's Discussion" candidate runs forward past the
100-char end-anchor skip and swallows later sections, because the `>=3 Item refs`
TOC-skip heuristic doesn't trip. Fixed in-fixture by using a realistically dense
TOC (documented in `sample_10k.html`). Worth knowing as a real parser limitation
on filings with unusually short TOCs.

**Verification** — `.venv/bin/python -m pytest` → **53 passed**. `ruff check
backend/tests` → clean. DB tests confirmed isolated (no `.db` file written).

**Now unblocked / next iteration** — **T1 part 2: ruff + mypy config + type-hint
backfill.** Baseline already measured: `ruff check backend/app` = **1** issue
(unused `pathlib.Path` import in `parse_filings.py`); lenient `mypy backend/app` =
**15** errors in 9 files (mostly `var-annotated` + a few real ones in
`parse_filings`/`metrics`/`llm_analysis`/`rss_ingest`). `main.py`/`api.py` add 7
more ruff issues (intentional "legacy kept for reference" `F811`s) — scope the lint
gate to `backend/app` first. ⚠️ **These fixes necessarily edit the same 22 files
that hold the uncommitted cleanup-pass diff** — so the next iteration must FIRST
resolve that working tree (commit the cleanup pass, or have the user confirm) to
avoid bundling WIP. Then T1 part 3 = GitHub Actions CI (pytest + ruff + mypy).

### 2026-06-24 — T1 SAFETY NET (CI): GitHub Actions

**What changed** — Added `.github/workflows/ci.yml` (purely additive): on every
push / PR it sets up Python 3.13, installs `requirements.txt` +
`requirements-dev.txt`, and runs `pytest`. Offline by design (SEC/Groq
monkeypatched, DB in-memory) so CI needs no secrets. Validated the YAML parses
and that the exact CI command (`pytest`) is green locally (53 passed).

**Deliberately pytest-only for now** — ruff + mypy steps are omitted until
`backend/app` actually passes them (1 ruff + 15 mypy issues outstanding); adding
them now would make CI red. They join the workflow in the ruff/mypy bullet. CI
activates on the user's next push (the leaked-key rotation should happen first).

### 2026-06-24 — User decision + T3: root README

**Decision recorded** — Asked the user how to handle the uncommitted 806-line
cleanup pass (it blocks ruff/mypy + all of T2, which edit those 22 files). They
chose **"leave it; additive-only"**: do NOT touch the uncommitted files, ship only
new-file units until they commit the cleanup pass themselves. So T1-ruff/mypy and
all of T2 are **parked** pending the user committing that working tree.

**What changed (T3)** — Added a root `README.md` (additive, new file). Quick-start
focused (clone → venv → `pip install` → `cp .env.example .env` + `SEC_USER_AGENT`
→ run CLI `python -m backend.main` or API `uvicorn backend.api:app --reload`),
with a CI badge, the compact pipeline diagram, the exact blend formula (verified
against `opinion.py`: weights `.25/.20/.20/.15/.20`), the five-dimension table,
the test command, and the free-data-source list. `LEARNINGS.md` stays the deep
reference. The repo previously had only an empty `backend/Readme.md`.

**Verification** — Markdown fences balanced; blend weights cross-checked against
source; entry-point commands confirmed (`main.py` has a `__main__`/`main()` that
calls `init_db()`; `api.py` exposes `POST /analyze` with `{company_name, ticker?}`).

**Now unblocked / next iteration** — While the cleanup pass stays uncommitted, the
only remaining additive (no-WIP) candidate is T3's *prune-unused-deps* (edits only
`requirements.txt`; needs grep verification — note `requirements.txt` looks
pip-freeze-style, so confirm it's a direct-deps list before pruning). Everything
higher-priority (T1 ruff/mypy, all T2) and all features (T4/T5) remain blocked —
T4/T5 also gated on T1 being *fully* done. The cleanest path forward is for the
user to **commit the cleanup pass**, which immediately unblocks T1-ruff/mypy → T2.

### 2026-06-25 — Cleanup pass committed → T0 `.env.example` re-track + T1 lint/type gate

**Context unblock** — the user committed the 806-line "cleanup pass" as `9b3234a`
("new changes"): the exact 22-file docstring/wiring diff from §7/§9 that every
later tier was parked behind (T1-ruff/mypy and all of T2 edit those same files).
With it committed the working tree is clean and those tiers are unblocked.
Confirmed the lint/type **baseline is unchanged** by the cleanup pass (it added
docstrings + wiring, not annotations): still **1 ruff + 15 mypy**.

**T0 follow-up (commit `f9bb8f7`)** — `9b3234a` also *deleted* the tracked
`.env.example` that T0 added (its diff showed `.env.example | 21 ------`); the file
survived only as an untracked copy on disk. Re-added it so the repo keeps the
secret-free template. Verified secret-free first — all 6 vars (`SEC_USER_AGENT`,
`GROQ_API_KEY`, `DATABASE_URL`, `RAW_FILINGS_DIR`, `REQUEST_TIMEOUT`,
`MAX_REQUESTS_PER_SECOND`) empty/placeholder; `.gitignore`'s `!.env.example`
negation keeps it trackable.

**T1 lint/type gate (commit `7bb0e48`)** — stood up the static-analysis gate on
`backend/app`, driving all 16 baseline issues to zero:
- **Config** (`pyproject.toml`): `[tool.ruff]` + `[tool.ruff.lint]` (default
  `E4/E7/E9/F`, pinned for version-stability; `target py313`) and `[tool.mypy]`
  (`files=["backend/app"]`, `ignore_missing_imports`, `py313`). Deliberately **not**
  `--strict`: the gate catches real type errors without demanding full annotation
  coverage (strict would surface hundreds of trivial ones and stall the loop).
- **1 ruff fix**: removed the unused `pathlib.Path` import (`F401`).
- **15 mypy fixes** — several real latent bugs, not just annotations:
  - A `_SectionCandidate` **TypedDict** for the heterogeneous candidate dicts in
    `parse_filings` — one type fixed *four* errors at once (the `var-annotated`,
    the `object`-typed `word_count >=` comparison, and both
    `Incompatible return value (object vs str)`).
  - `var-annotated`: `category_sentences` (risk/moat/business_model),
    `category_articles` (geopolitics), `changes` (opinion), `formatted` (metrics),
    `seen_starts`.
  - `parse_filings`: `filings.sort()` → `sorted()` — `.scalars().all()` returns an
    immutable `Sequence[Filing]` (no `.sort()`); `sorted()` is also non-mutating,
    strictly better.
  - `metrics`: `filtered = list(rows)` (was assigning a `Sequence` to a `list` var).
  - `rss_client`: `fetch_feed` now returns `feedparser.FeedParserDict` — it was
    annotated `-> dict`, which made mypy reject the legitimate `.entries` access in
    `rss_ingest`.
  - **`llm_analysis` (real bug):** `response.choices[0].message.content` is
    `str | None` but was passed straight to `json.loads`. Added an
    `if not raw: raise ValueError(...)` guard — a `None`/empty completion would
    previously have raised `TypeError`; it now degrades cleanly with a meaningful
    message through the existing `except`.
- **CI** (`ci.yml`): added `Lint (ruff check backend/app)` + `Type-check
  (mypy backend/app)` steps before the test step; refreshed the header comment.
  Still fully offline — no secrets.

**Verification** — `ruff check backend/app` clean; `mypy` → "no issues found in 22
source files"; `pytest` → **53 passed**; `ci.yml` parses (`yaml.safe_load`) and the
exact CI commands were dry-run locally, all green.

**Scope held deliberately** — gate scoped to `backend/app` (the core library).
`main.py` / `api.py` still carry **7** intentional `F811` "legacy kept for
reference" duplicate defs; removing/linting those is a distinct T3-cleanup unit,
not part of the type gate.

**Now unblocked / next iteration** — **T1 is complete** (pytest ✅, CI ✅, ruff+mypy
gate ✅). Highest-priority open work moves to **T2 ROBUSTNESS**, whose `backend/app`
edits are no longer blocked. Best first T2 unit: the **`load_dotenv` path bug**
(config.py — a bare `load_dotenv()` searches CWD-upward and misses
`backend/app/.env` when launched from the repo root, so the Groq key silently
fails to load and the LLM degrades to rule-only). Then CORS scope, drop
`verify=False`, structured logging, externalize scoring keywords/weights,
LLM-validation retry+fallback. Adjacent small cleanup: the 7 entry-point `F811`s.
T0 key rotation remains the only ⏳ user-blocked item.

### 2026-06-25 — T2 ROBUSTNESS (part 1): CWD-independent `.env` loading

**The bug** — `config.py` called a bare `load_dotenv()`, which searches *upward
from the current working directory*. Empirically (this machine): launched from the
repo root it loads `./.env` and the Groq key *is* present — so it looks fine and
hid the defect. But the search is CWD-dependent: a process launched from outside
the repo tree (a systemd service, an installed console entry point, any other cwd)
finds **no** `.env`, so `GROQ_API_KEY` silently stays unset and `llm_analysis`
quietly degrades to rule-only output with no error. (This corrects the T1-entry's
guess that it "misses `backend/app/.env` from the repo root" — the real trigger is
launching from *outside* the tree. Verified bug→fix by importing `config` from
`/tmp`: Groq key empty before, loaded after.)

**Also surfaced** — there are **two** `.env` files on disk: the canonical repo-root
`./.env` (exactly the 6 vars `config.py` reads, matching `.env.example`) and a
legacy `backend/app/.env` (those 6 + the dead `NEWS_API_*` / `PROCESSED_DATA_DIR`
vars T0 already stopped reading). Bare `load_dotenv()` made *which* one wins depend
on the launch dir — another facet of the nondeterminism.

**The fix (commit `8a1ed46`)** — extracted `_load_env_files(*paths) -> list[Path]`:
loads each existing `.env` by its **absolute path** (`override=False`, so a value
already in the real environment still wins) and returns what it loaded. At import
we call it with `(REPO_ROOT/".env", BACKEND_DIR/"app"/".env")` — repo-root
canonical first, legacy fallback second — both resolved relative to `__file__`, so
loading no longer depends on the cwd. Moved `BACKEND_DIR`/`REPO_ROOT` above the
call so they're in scope for it.

**Tests** — new `backend/tests/test_config.py` (4): explicit-path load,
skip-missing, no-override (real env wins), and first-path-wins precedence (why
repo-root beats legacy). All use throwaway `tmp_path` `.env` files — never the
developer's real `.env` — so they stay fully offline / CI-safe.

**Verification** — `pytest` **57 passed** (53 + 4); `ruff check backend/app` clean;
`mypy backend/app` clean; manual `/tmp` import confirms the Groq key now loads
regardless of launch directory.

**Now unblocked / next iteration** — T2 continues. Remaining T2 items (all edit
`backend/app`): drop `verify=False` (TLS verification disabled in `sec_client.py`
and `rss_client.py`), tighten CORS (`allow_origins=["*"]` in `api.py`), structured
`logging` over bare `print`, externalize scoring keywords/weights, LLM-validation
retry+fallback. Smaller adjacent cleanup: the 7 entry-point `F811`s. (T0 key
rotation still ⏳ user-side.)

### 2026-06-25 — T2 ROBUSTNESS (part 2): enable TLS verification

**The hole** — two outbound HTTP clients passed `verify=False` to httpx, which
*disables TLS certificate verification entirely*: `rss_client.py` (Google News
RSS) and `article_extractor.py` (full-article fetch). A network attacker can
present a forged certificate and MITM those fetches — the app would ingest
poisoned news/article content with no warning. (`sec_client.py` and
`company_lookup.py` were already fine — they omit `verify`, so httpx defaults to
verification ON.)

**The fix (commit `d970560`)**
- New `backend/app/http_client.py` — a single `make_http_client(**kwargs)` factory
  that applies `verify=settings.tls_verify` unless the caller passes an explicit
  `verify`. One place now owns the outbound-HTTP security posture.
- New config flag `tls_verify` (env `TLS_VERIFY`), default **True** (secure); only
  an explicit false-y value (`false/0/no/off`) disables it — for someone behind a
  trusted TLS-intercepting corporate proxy. Documented in `.env.example`.
- `rss_client.py` + `article_extractor.py` build their clients via
  `make_http_client(...)` with `verify=False` gone; the now-unused `import httpx`
  was dropped from both, and `rss_client`'s "verify=False is fine for a hobby
  project" docstring note was corrected.

**Tests** — new `backend/tests/test_http_client.py` (4): the factory defaults to
`verify=settings.tls_verify`, honors the flag when flipped, lets an explicit
`verify=` kwarg win, and the *shipped* default is `True`. A `_ClientRecorder`
(monkeypatched over `httpx.Client`) captures the kwargs without opening a socket
— fully offline.

**Verification** — `pytest` **61 passed** (57 + 4); `ruff check backend/app` clean;
`mypy backend/app` clean (23 files now, with the new module); `grep verify=False`
finds only a docstring + the override test — no live insecure clients.

**Now unblocked / next iteration** — T2 continues. Remaining: tighten CORS
(`allow_origins=["*"]` in `api.py` — the secure default is a judgment call, so make
it env-configurable without changing the default, or surface to the user),
structured `logging` over bare `print`, LLM-validation retry+fallback (self-
contained in `llm_analysis.py`, cleanly mockable), externalize scoring
keywords/weights. Optional consistency: route `sec_client`/`company_lookup`
through `make_http_client` too. Adjacent: the 7 entry-point `F811`s. (T0 key
rotation still ⏳ user-side.)

### 2026-06-25 — T2 ROBUSTNESS (part 3): bounded LLM retry + graceful fallback

**The gap** — `generate_llm_analysis` made *one* Groq call and, on any exception
(transient network, 429 rate limit, or off-schema/empty JSON from the stochastic
model), printed a notice and returned `None` — discarding the entire AI narrative
on a single blip. No retry at all.

**The fix (commit `b95d3a5`)** — extracted `_request_analysis(client, msg)` (one
call+parse+validate round-trip that raises on failure) and wrapped it in a bounded
retry inside `generate_llm_analysis`: up to `LLM_MAX_ATTEMPTS` (2) tries with a
small linear backoff (`LLM_RETRY_BACKOFF_SECONDS`), then the same graceful degrade
to `None`. Retrying is effective here precisely because the model is stochastic —
a fresh attempt frequently returns valid JSON — and transient network / rate-limit
errors clear on their own.

**Tests** — new `backend/tests/test_llm_analysis.py` (4): no-key short-circuit
(never calls), first-try success (1 call), retry-then-success (2 calls), and
exhaust-then-`None` (exactly `LLM_MAX_ATTEMPTS` calls). `Groq` is stubbed and
`_request_analysis` replaced with a controllable fake, with `time.sleep` patched
out — no network, no real delay.

**Verification** — `pytest` **65 passed** (61 + 4); `ruff` + `mypy backend/app` clean.

**Now unblocked / next iteration** — T2 remaining: make CORS `allow_origins`
env-configurable in `api.py` (keep the permissive default — the secure default is
a deploy-time judgment call), structured `logging` over bare `print` (incl. this
LLM notice + the geopolitics/ingest prints), externalize scoring keywords/weights.
Optional: route `sec_client`/`company_lookup` through `make_http_client`. Adjacent:
the 7 entry-point `F811`s. (T0 key rotation ⏳ user-side.)

### 2026-06-25 — T2 ROBUSTNESS (part 4): env-configurable CORS

**The gap** — `api.py` hardcoded `allow_origins=["*"]`, so any website could call
the API and there was no way to restrict it short of editing code.

**The fix (commit `e68aa01`)** — added a `cors_allow_origins` setting (env
`CORS_ALLOW_ORIGINS`, comma-separated) parsed by a small `_parse_csv_env` helper;
`api.py` now reads `settings.cors_allow_origins`. The default stays `"*"` → `["*"]`
(behavior unchanged), but an operator can set an allowlist (e.g.
`https://app.example.com`) to lock it down. Documented in `.env.example`. The
permissive default is intentional — the *secure* value is a deploy-time judgment
call (which origins?), so the unit adds the knob without guessing it (an actual
default tightening would be a user decision).

**Tests** — new `backend/tests/test_cors.py` (4): `_parse_csv_env` (wildcard,
multi-value + whitespace trimming, blank-dropping) and a FastAPI `TestClient` CORS
**preflight** asserting the default reflects any origin. The preflight is answered
by the middleware itself, so the `/analyze` pipeline never runs — fully offline.

**Verification** — `pytest` **69 passed** (65 + 4); `ruff` + `mypy backend/app`
clean. (`api.py` is outside the `backend/app` gate, so it's covered by the test,
not lint/type — a reason to widen the gate later.)

**Now unblocked / next iteration** — entering the timebox wrap-up window. Small
completable leftover: route `sec_client`/`company_lookup` through `make_http_client`
so `TLS_VERIFY` governs *all* outbound calls uniformly (today only news/article
do). Larger, deferred past the window: structured `logging` over `print`,
externalize scoring keywords/weights, the 7 entry-point `F811`s. (T0 key rotation
⏳ user-side.)

### 2026-06-25 — T2 ROBUSTNESS (part 5): uniform TLS via the client factory

**The loose end** — part 2 added `make_http_client` but only converted the two
`verify=False` callers. `sec_client.py` (3 sites) and `company_lookup.py` still
built `httpx.Client` directly, so `tls_verify` (and any `TLS_VERIFY=false` for a
trusted proxy) governed only the news/article fetches, not the SEC calls.

**The fix (commit `ba103a5`)** — routed both through `make_http_client`. `import
httpx` now lives in exactly one module (`http_client.py`), so every outbound call
shares one configurable TLS posture. Pure refactor — default behavior unchanged
(verification stays on).

**Tests** — `test_http_client.py` +2 routing tests: `company_lookup` and
`sec_client` each construct via `make_http_client` (a fake context-manager client
returns a fixed payload, so no network and no `_throttle` sleep on the first
call). 69 → 71.

**Verification** — `pytest` **71 passed**; `ruff` + `mypy backend/app` clean; grep
confirms `import httpx` only in `http_client.py`. The TLS thread is now complete
(factory + flag + all callers + docs + tests).

**Now / next** — in the timebox wrap-up window. T2 *security* items are done (`.env`
loading, TLS×2 → uniform, LLM retry, CORS). Remaining T2 is larger and deferred
past the landing: structured `logging` over `print`, externalize scoring
keywords/weights. A clean small candidate that ties off **T1**: widen the lint gate
to `main.py`/`api.py` with a per-file-ignore for their *intentional* `F811` "legacy
kept for reference" defs (non-destructive — the author kept that code on purpose).
(T0 key rotation ⏳ user-side.)

### 2026-06-25 — T1 capstone: widen the ruff gate to the whole backend

**What** — the lint gate ran only on `backend/app`; the entry points were
unchecked. The blocker was `main.py`'s live cruft: an unused `import json` (F401 —
leftover scaffolding for the commented legacy `main()` reference block) and a
duplicate `db/ingest/fundamentals/opinion` import block (F811×5) re-imported
verbatim in the ACTIVE section below it. Removed both — the commented "kept for
reference" block and the active code are untouched; those imports are simply
declared once now.

**Fix (commit `165974e`)** — `ruff check backend` (CI) now covers app + entry
points + tests, clean, **with no per-file-ignores** (the cruft was removed, not
suppressed). `api.py` was already clean. mypy stays scoped to `backend/app` —
widening it would need real type work on the entry points (future).

**Verification** — `ruff check backend` clean; `main.py` compiles and keeps its
`if __name__ == "__main__"` guard (so dropping the duplicate imports changed no
runtime behavior); `mypy backend/app` clean; `pytest` **71 passed**.

**T1 is now fully complete**: pytest (71) + ruff (whole `backend`) + mypy
(`backend/app`) all gated in CI.

### 2026-06-25 — T0 CLOSED: user rotated the leaked keys

The user rotated the leaked Groq + News API keys provider-side — the one item the
loop could not do autonomously (a real secret cannot be faked). This neutralizes
the credentials reachable in public git history (committed in `1e2124b`/`f417aa6`,
surfaced in the T0 entry above). **T0 is now fully closed.** A full history scrub
(`git filter-repo` + force-push) remains optional and is left to the user
(destructive; the loop won't force-push).

### 2026-06-25 — T1: mypy gate extended to the entry points

**What** — `mypy` covered only `backend/app`; `main.py` and `api.py` were
type-unchecked. They already pass cleanly (verified), so widening is free:
`[tool.mypy] files` now lists `backend/app` + `main.py` + `api.py`, and the CI step
matches. Tests stay out (fixtures/monkeypatching aren't worth strict typing).

**Fix (commit `ff5d570`)** — the static-analysis gate is now fully tied off: **ruff
over the whole `backend` tree, mypy over the library + both entry points.**

**Verification** — `mypy` clean on **25** source files (was 23, +`main.py`/`api.py`),
via both the explicit CI command and bare `mypy` (config `files`); `ruff check
backend` clean; `pytest` **71 passed**.

**Now / next** — T1 is maximally done. Next backlog item: **structured `logging`
over `print`** (~38 diagnostic prints: `ingest.py`(30) / `fundamentals.py`(6) /
`opinion.py` / `llm_analysis.py`). A library writing progress to stdout is poor form
(the API server inherits it). Plan: per-module `logging.getLogger(__name__)`,
convert diagnostics to `info`/`warning`, add `logging.basicConfig` in the CLI
(`main.py`) to keep progress visible; do it in 2 units (smaller modules first, then
`ingest.py`). Then externalize scoring keywords/weights.

### 2026-06-25 — T2 ROBUSTNESS (part 6): structured logging foundation

**The problem** — library modules `print()`-ed progress/diagnostics straight to
stdout: wrong for a library (the API server inherits the spew; callers can't
control verbosity).

**The fix (commit `877af61`)** — introduced the logging convention and converted
the three smaller modules:
- `llm_analysis` / `opinion` / `fundamentals`: a module-level
  `logging.getLogger(__name__)`; progress → `logger.info`, the LLM degradation
  notice → `logger.warning`, verbose per-tag/per-unit lines → `logger.debug`.
- `main.py` (CLI): `logging.basicConfig(level=INFO, format="%(message)s")` at the
  top of `main()` so progress stays visible and *reads like the old prints*; the
  API path inherits uvicorn's logging config.
- Net CLI effect: info progress looks unchanged; the verbose per-tag/unit lines
  now sit at DEBUG (quieter by default, available with `DEBUG`).

**Tests** — `test_llm_analysis.py` +1 `caplog` test (the exhausted-retry path logs
a `WARNING`). 71 → 72. Smoke test confirmed `basicConfig` shows info plainly and
hides debug.

**Verification** — `pytest` **72 passed**; `ruff check backend` + `mypy` clean.

**Now / next** — **`ingest.py` (28 prints)** is the one remaining print-heavy module
→ its own conversion unit (same convention: progress/download/save → `info`,
`except`-handler failures → `warning`/`error`, verbose → `debug`; no new
basicConfig needed). After that, structured logging is done; then externalize
scoring keywords/weights.

### 2026-06-25 — T2 ROBUSTNESS (part 7): ingest.py logging → migration complete

**The fix (commit `2de664d`)** — converted `ingest.py`, the last print-heavy library
module (28 prints), with the established convention: progress / downloads / saves /
end-of-run summaries → `info`; per-filing status (already-exists, URL backfill,
local-file-present, deleted, already-missing) → `debug`; `except`-handler failures
(download / process / delete) → `warning`. **`backend/app` is now fully
print-free.** The CLI (`main.py`) still owns user-facing report output via `print`,
with `basicConfig(INFO)` keeping progress visible.

**Verification** — `pytest` **72 passed**; `ruff check backend` + `mypy` clean; grep
confirms no `print()` remains in `backend/app`.

**Structured logging is DONE.** The only remaining T2 item is externalize scoring
keywords/weights (a larger refactor across the 4 scoring modules).

### 2026-06-25 — T2 ROBUSTNESS (part 8): externalize scoring config — risk (1/4)

**The fix (commit `1377822`)** — began externalizing the keyword scorers' tunable
data. Moved risk's keyword regex lists, category weights, and caps out of `risk.py`
into `backend/app/scoring/keywords.toml`, loaded once via a new `_keyword_config`
module (stdlib `tomllib`; regex patterns live in TOML *literal* strings, so
backslashes need no escaping — a JSON file would have needed ugly double-escaping).
`risk.py` keeps its module-level names (`RISK_KEYWORDS` / `RISK_WEIGHTS` /
`CATEGORY_CAP` / `TOTAL_CAP`), now assigned from the loaded table, so scoring logic,
callers, and tests are untouched.

**Fidelity guarantee** — the TOML was *generated programmatically* from the existing
in-memory data with a round-trip assertion (`tomllib.loads(text) == original`), so
the move is byte-for-byte faithful — no hand-transcription of the 60+ patterns.

**Tests** — `test_scoring_config.py` (3): the loader returns the expected tables,
keywords/weights align, and every externalized regex still `re.compile`s (guards
against any TOML-escaping corruption). 72 → 75; the 15 existing risk tests pass.

**Now / next** — same treatment for the other 3 scorers (each its own unit): `moat`,
`business_model`, `geopolitics`. geopolitics differs (news×filing fusion), so check
its data shape. Each adds a `[scorer]` section to keywords.toml + swaps its
hardcoded dicts for `scorer_config(...)`.

### 2026-06-25 — T2 ROBUSTNESS (part 9): externalize moat / business_model / geopolitics (2–4/4)

Applied the risk pattern (part 8) to the other three scorers — each its own commit,
each round-trip-faithful (generated from the live module + asserted
`tomllib.loads == original`), each verified by the existing scoring tests + ruff/mypy:
- **moat** (`1dd621d`) — like risk plus a `base_score`; the semiconductor-leaning
  keywords (`euv`, `photolithography`, …) are now a data-file edit to generalize.
- **business_model** (`7ff76e3`) — two-sided: `positive_weights` + `negative_weights`
  sub-tables, plus its two caps + base score.
- **geopolitics** (`27947a6`) — the fusion scorer: two keyword maps (`keywords` = news
  events, `exposure_keywords` = filing language) + weights. `FULL_TEXT_ARTICLE_LIMIT`
  stays in code (operational, not scoring data). Converted with a marker +
  brace-matching script rather than transcribing ~200 lines of regex by hand.

**T2 ROBUSTNESS is now COMPLETE.** All four keyword scorers source their lists +
weights from `backend/app/scoring/keywords.toml` via `_keyword_config`; the scoring
modules are logic-only. The generic `scorer_config(name)` loader handles all four
shapes (single/two-sided weights, one/two keyword maps).

**Verification** — `pytest` **75 passed**; `ruff check backend` + `mypy` clean; each
module confirmed loading its categories from TOML.

**Now / next** — T0, T1, T2 all ✅. Remaining is feature/cleanup work: T3 (async rate
limiter), T4 signature features (confidence, trajectory, forensic flags, backtesting),
T5 reach features. A natural point to check direction with the user.

### 2026-06-25 — T4 SIGNATURE FEATURES (1): analysis confidence meta-score

Resuming for the user's 3.5h absence (timebox now until ~7:17 PM). T0/T1/T2 are
complete, so moving into T4 — **safe, additive** feature units only while
unattended (the T3 async-rate-limiter is an invasive whole-codebase async rewrite
of working code; deferred-by-judgment, not done unattended).

**The feature (commit `2b9c33e`)** — `compute_analysis_confidence()` in `opinion.py`;
`build_full_opinion` now returns a `confidence` block (`{score 0-100, level
high/moderate/low, factors}`). It scores how much real data backs the five meters:
filing sections found (Risk Factors 25 / Business 20 / MD&A 10), financial metrics
loaded from XBRL (4 pts each, cap 20), a YoY comparison (15), and live news analyzed
(10). Sparse data → low confidence, so a data-starved opinion isn't read as strong.
Purely additive (new output field; scores/blend untouched), defensive against
missing/None inputs.

**Tests** — `test_confidence.py` (4): full→100/high, none→0/low,
filing-text-only→55/moderate, None-metrics-don't-count + odd inputs safe. 75 → 79;
`test_opinion` confirms `build_full_opinion` still passes end-to-end.

**Next** — T4 continues: score **trajectory** (multi-year overall-score history),
then forensic red-flag detection, then backtesting.

### 2026-06-25 — T4 SIGNATURE FEATURES (2): forensic red-flag scorer

**The feature (commit `eef191a`)** — new `backend/app/scoring/forensic.py`, a keyword
scorer (same engine as risk.py, primitives reused) for accounting/disclosure red
flags: going-concern, restatement, material weakness, impairment, related-party,
liquidity/covenant, SEC investigation, auditor change (8 categories in keywords.toml
`[forensic]`). `build_full_opinion` scans risk-factors/MD&A/business text and adds a
discrete `forensic` block (`{total_forensic_score, flags, evidence_sentences, ...}`).
**Crucially NOT folded into the weighted overall score** — flags are surfaced
explicitly with evidence so a real red flag is never averaged away by the blend.

**Tests** — `test_forensic.py` (5): clean → no flags, going-concern fires with
evidence, multiple flags detected, keyword/weight alignment, score capped [0,100].
79 → 84; `test_opinion` confirms `build_full_opinion` still works end-to-end.

**Verification** — `pytest` **84 passed**; `ruff` + `mypy` clean (27 files).

**Next** — T4 score **trajectory** (check `change_detection` for reusable
filing-parsing plumbing first; a light YoY-direction block if a true multi-year
re-score is too heavy for unattended work). Backtesting needs external price/outcome
data → will STOP-and-surface rather than fake.

### 2026-06-25 — T4 SIGNATURE FEATURES (3): multi-year score trajectory

**The feature (commit `ed710e5`)** — `build_score_trajectory()` in
`change_detection.py`: the risk / business-model / moat **text** scores across the
company's last N (default 4) annual filings, oldest→newest, plus a per-dimension
trend (latest delta + up/down/flat). Reuses the existing filing-parse plumbing
(`get_latest_annual_filings`, generalized from `get_latest_two`;
`extract_sections_from_filing`) and the text scorers. **Only the text-based scores
get a trajectory** — financials are point-in-time XBRL facts and geopolitics is live
news, so neither has a per-filing history. Best-effort: filings whose cached HTML
can't load are skipped. `build_full_opinion` surfaces a `score_trajectory` block
(additive; blend untouched). `test_opinion` mocks it (it hits the DB, like
`detect_filing_changes`).

**Tests** — `test_trajectory.py` (4): trend direction (up/down/flat), <2 points→no
trends, oldest→newest ordering, skips unloadable filings. 84 → 88; `ruff`+`mypy` clean.

**Known redundancy (noted, not fixed)** — `build_full_opinion` now parses the latest
2 annual filings twice (in `detect_filing_changes` and `build_score_trajectory`).
Offline + bounded, so acceptable; consolidating would touch `detect_filing_changes`
(riskier) — a future attended optimization.

**Next** — backtesting needs external price/outcome data → will **STOP-and-surface**.
So next safe additive unit: wire the new confidence/forensic/trajectory signals into
the LLM prompt (so the narrative can cite them), or a contradiction unit.

### 2026-06-25 — T4 SIGNATURE FEATURES (4): feed new signals into the LLM prompt

**The feature (commit `3062ac0`)** — confidence / forensic / trajectory were in the
opinion output but invisible to the AI narrative. Wired them into the `llm_analysis`
user message (+ a system-prompt rule): ANALYSIS CONFIDENCE (weight conviction),
FORENSIC RED FLAGS (fired flags + an evidence sentence each → surface in `red_flags`),
SCORE TRAJECTORY (per-dimension direction → reference in thesis). Two pure helpers
(`_build_forensic_block`, `_build_trajectory_block`) render them; empty inputs
degrade to "None detected." / "Not enough filings". Additive — the message only
grows, the JSON schema is unchanged.

**Tests** — `test_llm_analysis.py` +4. 88 → 92; existing retry tests unaffected;
`ruff` + `mypy` clean.

**Next** — a **contradiction unit**: flag internal tensions (wide moat but forensic
flags; improving business-model trajectory against rising risk language; high
financial score but low confidence). Pure logic over the assembled opinion → clean +
testable. Backtesting still STOP-and-surface (needs price data).

### 2026-06-25 — T4 SIGNATURE FEATURES (5): contradiction detector

**The feature (commit `0efa4fc`)** — `detect_contradictions()` in `opinion.py`;
`build_full_opinion` adds a `contradictions` block. Pure logic over the assembled
opinion surfacing internal tensions: high overall score despite forensic flags (flags
sit outside the blend); wide moat alongside forensic flags; strong financials but low
confidence (thin data); little risk language but high geopolitical exposure (risk
understated); business-model trajectory up while risk trajectory also up (mixed YoY);
strong moat but weak business model (unusual split). Additive, defensive on partial
inputs.

**Tests** — `test_contradictions.py` (5): coherent → none, plus one per main rule.
92 → 97; `ruff` + `mypy` clean.

**Next** — surface the new T4 blocks (confidence, forensic, trajectory, contradictions)
in the CLI report (`main.py`) so the terminal user sees them (extract a pure formatter
for testability). Backtesting → STOP-and-surface (needs price data).

### 2026-06-25 — T4 SIGNATURE FEATURES (6): surface signals in the CLI report

**The feature (commit `ad543d1`)** — the confidence / forensic / trajectory /
contradictions blocks were in the opinion output (and the API + LLM saw them) but the
CLI terminal report didn't. Added a pure `format_signature_section(opinion) -> str`
formatter + a "Signature Signals" section to `main.py`'s report. Pure formatter →
unit-testable without capsys/pipeline.

**Tests** — `test_cli_report.py` (2): all blocks rendered; empty opinion degrades
(forensic line always "none detected", optional blocks omitted). 97 → 99; clean.

**Now / next** — the **5 T4 signature features** (confidence, forensic, trajectory,
contradictions — all wired into the LLM prompt + CLI report) are a coherent set.
Remaining T4 backtesting needs external price/outcome data → **STOP-and-surface**, and
T5 reach features mostly need new data sources / large scope. So the clean *additive*
runway pivots to **test-debt + docs**: expand coverage for under-tested modules
(`company_lookup` matching, `rss_ingest` dedup, `geopolitics` fusion, `metrics`) and
document the new T4 modules in the README / §5 file-map. Both safe + high-value
unattended.

### 2026-06-25 — Test-debt (1): company_lookup matching coverage

`company_lookup.find_company_match` (ticker > exact-name > partial-name match
precedence + CIK zero-padding) had no tests. Added `test_company_lookup.py` (6),
mocking the SEC ticker directory so it's fully offline: `normalize_name`,
ticker-match-wins, exact-name + zero-pad, partial-name, no-match→None, and a
ticker-match name-overlap tie-break (commit `abe5910`). Test-only, no source change.
99 → 105; `ruff`+`mypy` clean. Next test-debt target: `rss_ingest` dedup / query
building, then `geopolitics` fusion. (`metrics` is already covered by T1's
`test_metrics.py`.)

### 2026-06-25 — Test-debt (2): rss_ingest coverage

`rss_ingest` (Google-News RSS URL building, entry normalization with the
`published`→`updated` fallback, publisher-suffix title canonicalization, dedupe, and
the boolean search-query builder) was untested. Added `test_rss_ingest.py` (5),
mocking the feed (offline) — commit `b059f12`. Test-only. 105 → 110. Next: the
`geopolitics` news×filing fusion (`classify_articles` + overlap scoring), the most
complex untested module.

### Backlog status (mirror of the /timebox brief — keep in sync)
- **T0 SECURITY** — ✅ **complete**. Code remediation ✅ (untrack `.env`, fix
  `.gitignore`, add `.env.example`); `.env.example` re-tracked ✅ (`f9bb8f7`) after
  `9b3234a` silently dropped it. Key rotation ✅ **done by user (2026-06-25)** —
  leaked Groq + News API keys rotated, neutralizing the public-history exposure.
  (Optional, user-side: a `git filter-repo` history scrub.)
- **T1 SAFETY NET** — ✅ **complete**. pytest (71 tests) + ruff (whole `backend`
  tree) + mypy (`backend/app` + entry points) all gated in CI. ruff+mypy config +
  16-issue type-hint backfill (`7bb0e48`); ruff widened to the entry points with
  `main.py` cruft removed (`165974e`); mypy widened to the entry points
  (`ff5d570`). Static-analysis gate fully tied off.
- **T2 ROBUSTNESS** — ✅ **complete**. `.env` CWD-fix (`8a1ed46`), TLS → uniform
  (`d970560`/`ba103a5`), LLM retry+fallback (`b95d3a5`), env CORS (`e68aa01`),
  structured logging (`877af61`/`2de664d`), and all 4 scorers' keywords/weights
  externalized to `keywords.toml` (`1377822`/`1dd621d`/`7ff76e3`/`27947a6`).
- **T3 CLEANUP** — 🟦 root README ✅ (committed). Prune-unused-deps ✅ investigated
  → **no-op**: `beautifulsoup4`/`justext`/`courlan`/`dateparser` aren't unused —
  they're transitive deps of `trafilatura`/`htmldate`/`lxml` (pip reinstalls them
  regardless), and `requirements.txt` is pip-freeze-style, so pruning only loosens
  pins. Leave the freeze intact, or adopt a `requirements.in` (direct deps) +
  pip-compile flow — a user call, not done autonomously. Entry-point `F811`s ✅
  resolved in the T1 capstone (`165974e`). Async rate limiter ⏸ **deferred-by-
  judgment** — an invasive whole-codebase async rewrite of working code, too risky
  to run unattended; revisit attended.
- **T4 SIGNATURE FEATURES** — 🟦 mostly done (T0–T2 ✅; additive only while
  unattended). Confidence ✅ (`2b9c33e`), forensic ✅ (`eef191a`), trajectory ✅
  (`ed710e5`), signals→LLM ✅ (`3062ac0`), contradictions ✅ (`0efa4fc`), CLI surfacing
  ✅ (`ad543d1`). Remaining: backtesting → STOP-and-surface (needs price data). Clean
  additive runway now pivots to **test-debt + docs** (see latest log entry).
  (T3 async rewrite deferred-by-judgment.)
- **T5 REACH FEATURES** — ⬜ (insider/institutional, peer-relative, contradiction
  detector, RAG Q&A, frontend, watchlist/alerts, PDF export).

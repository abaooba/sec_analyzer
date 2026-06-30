# Changelog

Notable changes to **sec_analyzer**. The design keeps the AI *last* — every score is
explainable; the LLM only narrates on top of the numbers.

## [Unreleased] — 2026-06-29

### Factor exposure & performance attribution (new endpoint)

A new analytical dimension, separate from the SEC-filing pipeline: decompose a
portfolio (or a single stock/ETF) against the **Fama-French 5-factor + Momentum**
model. Additive — `/analyze` and its response are untouched.

- **New `POST /factor-attribution` endpoint.** Body is `{holdings:[{ticker,weight}]}`
  or a single `{ticker}`, plus optional `start_date` / `end_date` / `rolling_window`.
  Returns static factor betas + alpha (with std err / t / p / 95% CI / significance),
  rolling betas (statsmodels `RollingOLS`), and a **return-attribution waterfall**
  whose per-factor slices + alpha reconcile exactly to the total excess return.
- **New `backend/app/factors/` package** — `factor_data` (Ken French FF5 + Momentum
  CSVs, fetched through the shared `make_http_client` and disk-cached),
  `prices` (yfinance → returns → weighted portfolio), `regression` (one shared OLS
  fit feeding the summary and the waterfall), `attribution`, and `service` (the
  orchestrator; injectable price/factor loaders keep it fully offline-testable).
- **Data sources:** Ken French Data Library (factors, no key) + yfinance (prices,
  no key). The factor zips are cached under `FACTOR_CACHE_DIR` (`FACTOR_CACHE_TTL_HOURS`
  default 24h). The heavy quant stack (statsmodels / pandas / yfinance) is imported
  **lazily** at the endpoint, so app startup and the `/analyze` path are unaffected.
- **Config:** `FACTOR_DATA_BASE_URL`, `FACTOR_CACHE_DIR`, `FACTOR_CACHE_TTL_HOURS`.
- **Dependencies added** (runtime): numpy, pandas, scipy, statsmodels, yfinance
  (+ their transitive deps), pinned in `requirements.txt`.
- **Tests:** 40 new fully-offline tests (data parse/cache, returns/portfolio math,
  regression recovery, waterfall reconciliation, the orchestrator, and the endpoint
  wiring) — synthetic returns with known alpha/betas verify the estimates.
- **Docs:** `docs/factor-attribution.md` (frontend handoff), `…types.ts`, and a
  generated `…sample.json`; README + this changelog updated. (Streamlit/gradio
  dashboard intentionally omitted — the frontend lives in a separate repo.)

## [Unreleased] — 2026-06-25

A foundation-and-features pass (backlog tiers T0–T4). All changes are local; nothing
has been pushed.

### Security (T0)
- Stopped tracking `.env`; fixed `.gitignore`; added a secret-free `.env.example`
  (and re-tracked it after a later commit dropped it).
- Leaked Groq / News API keys rotated (user, provider-side).

### Safety net (T1)
- pytest suite stood up and grown to **141 offline tests** (no network, no secrets).
- `ruff` + `mypy` configured and wired into CI alongside pytest: ruff over the whole
  `backend` tree, mypy over `backend/app` + the entry points. 16 baseline lint/type
  issues fixed; `main.py` import cruft removed.

### Robustness (T2)
- `config`: `.env` now loads by an explicit, CWD-independent path, so the Groq key no
  longer silently fails to load when launched from outside the repo tree.
- **TLS verification enabled** — removed `verify=False`; all outbound HTTP now flows
  through one `make_http_client` factory governed by a `TLS_VERIFY` flag (secure
  default).
- LLM layer: bounded **retry + graceful fallback** around the Groq call.
- **CORS** allow-origins made env-configurable (`CORS_ALLOW_ORIGINS`).
- **Structured logging** replaces `print()` across the library (`backend/app` is
  print-free; the CLI keeps its formatted report output).
- Scoring **keywords / weights externalized** to `scoring/keywords.toml` (loaded via
  `_keyword_config`) for all five scorers — tunable / generalizable without code edits.

### Features (T4 — signature analytics)
All additive; none change the 0–100 blended score.
- **Confidence** meta-score — how much real data backs the opinion (filing sections,
  XBRL metrics, YoY data, news).
- **Forensic red-flag** scorer — going-concern, restatement, material weakness,
  impairment, … — surfaced as discrete flags with evidence (not in the blend).
- **Score trajectory** — risk / business-model / moat text scores across recent
  annual filings.
- **Contradiction detector** — internal tensions (e.g. a strong headline score
  undercut by a forensic flag).
- All four wired into the LLM prompt and the CLI report.

### Tests & docs
- Comprehensive offline coverage: all five scorers, the orchestrator blend, the four
  signature features, the `/analyze` endpoint, every HTTP client, config / loader, and
  the YoY / trajectory logic.
- README + `LEARNINGS.md` file-map updated for the new modules and output blocks.

### Parked (needs input or out of scope for unattended work)
- **Backtesting** + most **T5 reach features** (peer-relative, insider/institutional,
  RAG Q&A, frontend, PDF export) — need external data sources.
- **Async rate-limiter rewrite** — an invasive whole-codebase async rearchitecture;
  left for an attended session.
- **CORS secure default**, **peer set**, **git-history scrub** — deploy-time / user
  decisions.

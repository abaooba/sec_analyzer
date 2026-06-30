# Factor Exposure & Performance Attribution — `POST /factor-attribution`

A new, standalone endpoint (separate from `/analyze`). It takes a portfolio — or a
single stock/ETF — and decomposes its returns against the **Fama-French 5-factor +
Momentum** model: static factor betas, rolling betas, alpha, and a return-attribution
waterfall (how much of the return came from market vs. size vs. value vs. ... vs. the
portfolio's own idiosyncratic edge).

It answers the question every PM and allocator asks: *is this return alpha, or just
being paid for tilting toward small-cap value?*

> This is its own dimension of analysis (price/return based) and does **not** touch
> `/analyze` or its response. Nothing existing changes.

## Request

```jsonc
POST /factor-attribution
{
  "holdings": [                     // a portfolio...
    { "ticker": "AAPL", "weight": 0.6 },
    { "ticker": "MSFT", "weight": 0.4 }
  ],
  // ...or a single stock/ETF instead of holdings:
  // "ticker": "SPY",
  "start_date": "2020-01-01",       // optional, ISO; default ~5y ago
  "end_date":   "2024-12-31",       // optional, ISO; default today
  "rolling_window": 126             // optional; rolling-beta window in trading days
}
```

- `weight` defaults to `1.0`; weights are de-duplicated and **renormalized to sum to 1**.
- Provide **either** `holdings` **or** `ticker`. A single `ticker` is treated as a 100% position.

## Response

The full success shape and an error variant are in
[`factor-attribution.types.ts`](./factor-attribution.types.ts); a complete example
payload is in [`factor-attribution.sample.json`](./factor-attribution.sample.json).

On any data problem (unknown tickers, too little overlapping history) the endpoint
returns `{ "error": "..." }` instead — **check for `error` first**.

> **All returns are decimals** (`0.12` = 12%), not percentages. Multiply by 100 for display.

| Block | What it is | UI suggestion |
|---|---|---|
| `portfolio` | Echoed normalized holdings, the resolved date window, observation count, and any `dropped_tickers` (requested but had no price data) | Header / caption; surface `dropped_tickers` as a warning if non-empty |
| `full_sample` | Static regression over the whole window: `alpha` (daily + annualized, with significance), per-factor `betas` (each with std err / t / p / 95% CI / `significant`), `r_squared` | Betas as a bar chart (highlight `significant`); alpha as a stat with its CI |
| `rolling` | Rolling-window regression: parallel arrays on a shared `dates` axis — one beta series per factor, `alpha_annualized`, `r_squared` | Multi-line rolling-beta chart (one line per factor); R²-over-time sparkline |
| `attribution` | The waterfall: one `components` slice per factor (`beta × factor_avg_return`, annualized) plus a final `alpha` slice; the slices reconcile to `total_excess_return_annualized` | Waterfall bar chart, factors then alpha; the bars sum to the total |

### Notes for rendering

- **`rolling`** arrays are parallel: `betas[factor][i]`, `alpha_annualized[i]`, and
  `r_squared[i]` all correspond to the window ending on `dates[i]` (oldest → newest).
  Length grows with history (`observations = days − window + 1`); downsample client-side
  if needed. When history is shorter than one window, `available` is `false` and the
  arrays are empty — show "not enough history for a rolling view".
  *(The sample payload uses a short window so it stays small; production responses are larger.)*
- **`attribution.components`** is ordered factors-then-alpha. The last entry is
  `factor: "alpha"` (with `beta: null`). `explained_by_factors_annualized + alpha_annualized`
  equals `total_excess_return_annualized`; `residual_annualized` is the ≈0 rounding gap.
- **`significant`** (alpha and each beta) is `p_value < 0.05` — use it to de-emphasize
  exposures the data can't actually distinguish from zero.

## Deployment note (not a code change)

- The factor data comes from the free **Ken French Data Library** (daily FF5 + Momentum
  CSVs) and prices from **yfinance**; no API keys are required. Both are reached over the
  network at request time. The Ken French zips are disk-cached (`FACTOR_CACHE_DIR`,
  default 24h TTL via `FACTOR_CACHE_TTL_HOURS`), so only the first request per day pays
  the download.
- The first call to this endpoint imports the quant stack (statsmodels / pandas /
  yfinance) lazily — expect a slightly slower cold start on that one request.
- The same `CORS_ALLOW_ORIGINS` allowlist that governs `/analyze` governs this endpoint.

## Ready-to-paste prompt for the frontend repo

> The `sec_analyzer` backend has a new endpoint, `POST /factor-attribution`, separate from
> `/analyze` (which is unchanged). It decomposes a portfolio's — or a single ticker's —
> returns against the Fama-French 5-factor + Momentum model. Request body: either
> `holdings: [{ticker, weight?}]` or a single `ticker`, plus optional `start_date`,
> `end_date`, and `rolling_window` (trading days). On a data problem it returns
> `{error}` — handle that first. The success payload has four blocks: `portfolio`
> (echoed normalized holdings + window + `dropped_tickers`), `full_sample` (static
> regression: `alpha` with significance, per-factor `betas` each with t-stat / p-value /
> 95% CI / `significant`, `r_squared`), `rolling` (parallel arrays on a `dates` axis:
> per-factor beta series, `alpha_annualized`, `r_squared`), and `attribution` (a waterfall
> of per-factor contributions + an `alpha` slice that reconciles to the total). All returns
> are decimals (multiply by 100 for %). Build a dashboard: a rolling-beta line chart (one
> line per factor), an attribution waterfall bar chart, the static betas with their CIs,
> and alpha with its confidence interval. The exact types and a sample payload are in the
> backend repo at `docs/factor-attribution.types.ts` and `docs/factor-attribution.sample.json`.

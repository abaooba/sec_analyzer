# Cross-Sectional Fundamental Screen — `POST /screen`

A new, standalone endpoint (separate from `/analyze`). It takes a **universe of
tickers** and ranks them against each other on five classic quantitative metrics,
then flags the two failure modes a screen exists to catch — financial distress and
low earnings quality — and returns a ranked, color-coded table plus a ready-to-plot
**value-vs-quality** scatter.

The metrics:

| Metric | What it measures | Axis |
|---|---|---|
| **Piotroski F-Score** (0-9) | 9 binary fundamental-momentum tests (profitability, leverage/liquidity, efficiency) | quality |
| **Altman Z-Score** | bankruptcy/distress model — classic (with market cap) or book-value Z″ | distress flag |
| **Sloan accruals** | `(net income − operating cash flow) / avg assets`; high = earnings outrunning cash | quality / EQ flag |
| **ROIC** | `NOPAT / (equity + long-term debt)` — return on the capital employed | quality |
| **FCF yield** | `free cash flow / market cap` — how cheaply the market prices the cash generated | value |

> This is its own dimension of analysis (cross-company, point-in-time fundamentals)
> and does **not** touch `/analyze` or its response. Nothing existing changes.

## Request

```jsonc
POST /screen
{
  "tickers": ["AAPL", "MSFT", "NVDA", "GOOGL", "KO", "F"],
  "ingest": true,             // download each company's XBRL facts first (default true)
  "fetch_market_caps": true   // fetch market caps for FCF yield + classic Altman (default true)
}
```

Set `ingest: false` to screen only companies already in the DB (faster, offline).
Set `fetch_market_caps: false` to skip the market-cap fetch — the screen then falls
back to the book-value Altman model (Z″) and reports no FCF yield. The universe is
capped at 60 names (extras are returned in `truncated`).

## Response

The full shape is in **`screen-response.types.ts`**; a real payload is in
**`screen-response.sample.json`**. Top-level:

```jsonc
{
  "universe_size": 6,
  "unresolved": [],            // tickers no company matched
  "no_data": [],               // tickers with no usable annual fundamentals
  "flag_counts": { "distress": 1, "earnings_quality_risk": 2 },
  "medians": { "value_score": 50.0, "quality_score": 41.6 },
  "rows": [ /* ranked, best-first — see ScreenRow */ ],
  "scatter": { /* axis labels, quadrant medians, colored points */ }
}
```

Each **row** carries the raw metrics, their 0-100 cross-sectional `percentiles`,
the `quality_score` / `value_score` / `composite_score` (the rank key), the fired
`flags`, and per-metric `colors` for the table. `detail` has the full breakdown
(the 9 Piotroski tests, the Altman components, the ROIC build-up).

## Rendering guidance

1. **Ranked table** — one row per company, ordered by `rank`. Color each metric
   cell using `row.colors[metric]` (`green` / `amber` / `red` / `neutral`) so the
   UI matches the CLI/PNG. Show `f_score` as `x/9` and mark it partial when
   `f_score_available < 9`. Surface `flags` as chips: `distress` (⚠ red) and
   `earnings_quality_risk` (⚠ amber).
2. **Value-vs-quality scatter** — plot `scatter.points` with `value` on x and
   `quality` on y (both 0-100), colored by `point.color`. Draw quadrant lines at
   `scatter.median_value` / `scatter.median_quality` (or at 50/50). The top-right
   quadrant is the sweet spot (cheap **and** high quality); the bottom-right is the
   value-trap corner (cheap but low quality — often where the distress flag lands).
   Points only exist for companies with **both** axes; list the rest as "not
   plotted".

## Metric notes (so the UI can caption honestly)

- **Numbers are decimals** — `roic: 0.28` is 28%, `fcf_yield: 0.023` is 2.3%.
  `altman_z` is a raw score; every `*_score` and percentile is 0-100.
- **Altman model varies by data.** With a market cap we use the *classic* 5-factor
  Z (distress `< 1.81`); without one, the book-value **Z″** model (distress `< 1.1`).
  `altman_model` says which, and `distress_zone` already applies the right cut points
  — trust the zone, not a fixed threshold on the raw score. Book-value Z″ is
  conservative for firms with thin book equity (heavy buybacks) or large financing
  arms, so a "grey"/"distress" there isn't the same red alert as a low classic Z.
- **Accruals: lower is better.** Negative accruals (cash exceeds earnings) are
  benign; the `earnings_quality_risk` flag fires when accruals clear an absolute
  `0.10` or sit in the universe's worst quartile (needs ≥ 4 names).
- **Any metric can be `null`** when a company doesn't tag the underlying XBRL
  concept. Render missing as "—", never 0.

## CLI

The same engine backs a terminal report:

```
python -m backend.screen AAPL MSFT NVDA GOOGL KO F
```

It prints the color-coded table and an ASCII value-vs-quality scatter, and — when
`matplotlib` is installed (a dev-only dependency) — also writes a PNG of the scatter
to `data/screen_value_vs_quality.png`.

/**
 * TypeScript interfaces for the `POST /screen` response.
 *
 * Copy/adapt these into the frontend repo. The endpoint ranks a universe of
 * tickers on five classic fundamental metrics (Piotroski F-Score, Altman
 * Z-Score, Sloan accruals, ROIC, FCF yield), flags distress + earnings-quality
 * risks, and returns a ranked, color-coded table plus ready-to-plot
 * value-vs-quality scatter points.
 *
 * Number conventions: ratios are *decimals* (0.28 = 28% ROIC), Altman Z is a raw
 * score, and every `*_score` / percentile is 0-100. Any field may be `null` when
 * a company doesn't tag the underlying XBRL data — render defensively.
 *
 * On a bad request the endpoint returns `{ error: string }` instead of the
 * success payload, so handle that union first (see ScreenResponse).
 */

/** Request body: the universe to screen. */
export interface ScreenRequest {
  tickers: string[];              // e.g. ["AAPL", "MSFT", "NVDA"]
  ingest?: boolean;               // download each company's XBRL facts first (default true)
  fetch_market_caps?: boolean;    // fetch market caps for FCF yield + classic Altman (default true)
}

/** Which Altman model produced the score (drives the safe/grey/distress cut points). */
export type AltmanModel = "classic" | "z_double_prime" | null;

/** Distress zone from the Altman Z-Score. */
export type DistressZone = "safe" | "grey" | "distress" | "unknown";

/** Risk flags a row can carry. */
export type ScreenFlag = "distress" | "earnings_quality_risk";

/** Color name per metric cell (and per scatter point) — paint the UI to match. */
export type ColorName = "green" | "amber" | "red" | "neutral";

/** Per-metric color hints so the table matches the terminal/PNG coloring. */
export interface RowColors {
  f_score: ColorName;
  altman_z: ColorName;
  accruals: ColorName;
  roic: ColorName;
  fcf_yield: ColorName;
}

/** 0-100 percentile ranks of each metric within the screened universe. */
export interface RowPercentiles {
  f_score: number | null;
  roic: number | null;
  accruals: number | null;   // percentile of raw accruals (higher = worse)
  fcf_yield: number | null;
  altman_z: number | null;
}

/** One ranked company. `detail` carries the full metric breakdown (see below). */
export interface ScreenRow {
  rank: number;                    // 1-based, best composite first
  ticker: string;
  name: string;
  cik: string;
  period_end: string | null;       // fiscal-year end the metrics are computed on
  prior_period_end: string | null; // the prior year used for year-over-year tests
  market_cap: number | null;

  // Headline metrics
  f_score: number | null;          // Piotroski F-Score, 0-9
  f_score_available: number;       // how many of the 9 tests had data (< 9 = partial)
  altman_z: number | null;
  altman_model: AltmanModel;
  distress_zone: DistressZone;
  accruals: number | null;         // Sloan ratio; higher (more positive) = lower quality
  roic: number | null;             // decimal
  fcf_yield: number | null;        // decimal; null without a market cap
  earnings_yield: number | null;   // decimal; null without a market cap

  // Cross-sectional standing (0-100)
  percentiles: RowPercentiles;
  quality_score: number | null;    // blend of F-Score + ROIC + low accruals
  value_score: number | null;      // FCF-yield percentile
  composite_score: number | null;  // equal-weight blend of quality + value (the rank key)

  flags: ScreenFlag[];             // empty when clean
  colors: RowColors;

  detail: ScreenRowDetail;         // full metric breakdown
}

/** Full per-company metric detail (for tooltips / an expandable row). */
export interface ScreenRowDetail {
  piotroski: {
    f_score: number;
    tests: Record<string, boolean | null>; // 9 named tests; null = not computable
    tests_available: number;
    complete: boolean;
  };
  altman: {
    z_score: number | null;
    model: AltmanModel;
    zone: DistressZone;
    components: Record<string, number | null>; // x1..x5 (classic) or x1..x4 (Z'')
  };
  roic: {
    roic: number | null;
    nopat: number | null;
    invested_capital: number | null;
    tax_rate: number | null;
  };
  fcf: number | null;
  current: Record<string, number | string | null>; // raw current-year snapshot
  prior: Record<string, number | string | null>;   // raw prior-year snapshot
}

/** One plottable point for the value-vs-quality scatter. */
export interface ScatterPoint {
  ticker: string;
  value: number;    // 0-100 (x axis: FCF-yield percentile)
  quality: number;  // 0-100 (y axis)
  color: ColorName; // red = distress, amber = any flag, green = clean
  flags: ScreenFlag[];
}

/** The scatter block: axis labels, quadrant medians, and the points. */
export interface Scatter {
  x_label: string;
  y_label: string;
  median_value: number | null;    // draw a vertical quadrant line here
  median_quality: number | null;  // draw a horizontal quadrant line here
  points: ScatterPoint[];         // only companies with both axes present
}

/** The success payload. */
export interface ScreenSuccess {
  universe: string[];              // normalized (upper-cased, de-duped) tickers
  universe_size: number;           // how many companies were actually screened
  screened: number;                // alias of universe_size
  unresolved: string[];            // tickers no company matched
  no_data: string[];               // tickers with no usable annual fundamentals
  truncated: string[];             // tickers dropped past the 60-name cap
  flag_counts: { distress: number; earnings_quality_risk: number };
  medians: { value_score: number | null; quality_score: number | null };
  rows: ScreenRow[];               // ranked, best-first
  scatter: Scatter;
}

export interface ScreenError {
  error: string;
}

/** Handle the error branch first. */
export type ScreenResponse = ScreenSuccess | ScreenError;

/**
 * TypeScript interfaces for the `POST /factor-attribution` response.
 *
 * Copy/adapt these into the frontend repo. The endpoint decomposes a portfolio's
 * (or a single ticker's) returns against the Fama-French 5-factor + Momentum
 * model. Every numeric field is a plain JSON number; returns are *decimals*
 * (0.12 = 12%), not percentages — multiply by 100 for display.
 *
 * On any data problem the endpoint returns `{ error: string }` instead of the
 * success payload, so handle that union first (see FactorAttributionResponse).
 */

/** The six regression factors (RF is excluded — it defines the excess return). */
export type FactorKey = "Mkt-RF" | "SMB" | "HML" | "RMW" | "CMA" | "Mom";

/** Request body. Provide `holdings` (a portfolio) OR a single `ticker`. */
export interface FactorAttributionRequest {
  holdings?: Array<{ ticker: string; weight?: number }>; // weight defaults to 1.0
  ticker?: string;            // convenience: a single stock/ETF (100% position)
  start_date?: string;        // ISO date; default ~5 years ago
  end_date?: string;          // ISO date; default today
  rolling_window?: number;    // rolling-beta window in trading days (default 126)
}

/** One regression coefficient with its inference stats. */
export interface CoefficientStats {
  beta: number;               // the point estimate (slope)
  label: string;              // human-readable factor name, e.g. "Value (HML)"
  std_err: number;
  t_stat: number;
  p_value: number;
  conf_int: [number, number]; // 95% CI [low, high]
  significant: boolean;       // p_value < 0.05
}

/** Alpha = the intercept: average return unexplained by factor exposure. */
export interface AlphaStats {
  daily: number;              // daily alpha (decimal)
  annualized: number;         // daily x 252 (decimal)
  std_err: number;
  t_stat: number;
  p_value: number;
  conf_int_daily: [number, number]; // 95% CI on the daily alpha
  significant: boolean;       // is alpha statistically distinguishable from 0?
}

/** Full-sample (static) regression over the whole window. */
export interface FullSampleRegression {
  alpha: AlphaStats;
  betas: Record<FactorKey, CoefficientStats>;
  r_squared: number;
  adj_r_squared: number;
  n_obs: number;              // observations used in the fit
}

/**
 * Rolling-window regression. All arrays are parallel and share the `dates` axis
 * (oldest -> newest); `betas[factor][i]` and `alpha_annualized[i]` correspond to
 * the window ending on `dates[i]`. When history is shorter than one window,
 * `available` is false and the arrays are empty.
 */
export interface RollingRegression {
  window: number;             // window length in trading days
  available: boolean;
  observations: number;       // == dates.length
  dates: string[];            // ISO date per rolling window end
  betas: Record<FactorKey, number[]>;
  alpha_annualized: number[];
  r_squared: Array<number | null>;
}

/** One slice of the attribution waterfall. The final slice is `factor: "alpha"`. */
export interface AttributionComponent {
  factor: FactorKey | "alpha";
  label: string;
  beta: number | null;                          // null for the alpha slice
  factor_avg_return_annualized: number | null;  // null for the alpha slice
  contribution_annualized: number;              // beta x factor return (annualized)
  pct_of_total: number | null;                  // share of total; null if total ~ 0
}

/**
 * Return-attribution waterfall (annualized decimal returns). The components plus
 * alpha reconcile to `total_excess_return_annualized`; `residual_annualized` is
 * the (≈0) rounding gap.
 */
export interface Attribution {
  basis: "annualized_excess_return";
  total_excess_return_annualized: number;
  explained_by_factors_annualized: number;
  alpha_annualized: number;
  residual_annualized: number;
  components: AttributionComponent[];
}

export interface PortfolioMeta {
  holdings: Array<{ ticker: string; weight: number }>; // renormalized to sum to 1
  dropped_tickers: string[];   // requested tickers with no usable price history
  start_date: string;
  end_date: string;
  observations: number;
  first_date: string;
  last_date: string;
}

/** The success payload. */
export interface FactorAttributionSuccess {
  portfolio: PortfolioMeta;
  factor_model: string;        // "Fama-French 5 Factor + Momentum"
  factors: FactorKey[];
  full_sample: FullSampleRegression;
  rolling: RollingRegression;
  attribution: Attribution;
}

/** Error payload (unknown tickers, too little overlapping history, etc.). */
export interface FactorAttributionError {
  error: string;
}

export type FactorAttributionResponse =
  | FactorAttributionSuccess
  | FactorAttributionError;

export function isFactorAttributionError(
  response: FactorAttributionResponse,
): response is FactorAttributionError {
  return "error" in response;
}

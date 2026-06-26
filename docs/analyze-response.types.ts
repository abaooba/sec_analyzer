/**
 * Type definitions for the POST /analyze response.
 *
 * This is the contract the frontend consumes. It is documentation-grade:
 * copy/adapt into the frontend repo's own types. All four of the T4 fields
 * (`confidence`, `forensic`, `score_trajectory`, `contradictions`) are
 * additive and may be absent/empty on older or data-thin responses, so they
 * are typed optional — render defensively.
 *
 * Request body:  { company_name: string; ticker?: string }
 * Error case:    { error: string }   (e.g. company not found)
 */

export interface AnalyzeRequest {
  company_name: string;
  ticker?: string;
}

export interface AnalyzeError {
  error: string;
}

/** One of "high" | "moderate" | "low". */
export type ConfidenceLevel = "high" | "moderate" | "low";

/** How much real data backs the analysis. Surface near the overall score. */
export interface Confidence {
  /** 0–100. */
  score: number;
  level: ConfidenceLevel;
  /** Which inputs were present — good for a "why" tooltip. */
  factors: {
    risk_factors_text: boolean;
    business_text: boolean;
    mdna_text: boolean;
    /** Count of non-null XBRL metrics that loaded. */
    financial_metrics_present: number;
    year_over_year_data: boolean;
    /** Count of news articles pulled for the geopolitics signal. */
    news_articles_analyzed: number;
  };
}

/** Forensic red-flag categories that can fire. */
export type ForensicFlag =
  | "going_concern"
  | "restatement"
  | "material_weakness"
  | "impairment"
  | "related_party"
  | "liquidity_covenant"
  | "sec_investigation"
  | "auditor_change";

/**
 * Accounting/disclosure red flags from the filing text. Deliberately NOT part
 * of `overall_score` — render as discrete warnings, never averaged in.
 */
export interface Forensic {
  /** 0–100, higher = more/heavier flags. Informational; not blended in. */
  total_forensic_score: number;
  /** The categories that fired (empty when nothing detected). */
  flags: ForensicFlag[];
  category_scores: Record<string, number>;
  /** Matched keyword -> hit count, per category. */
  matched_keywords: Record<string, Record<string, number>>;
  /** Up to ~2 quoted filing sentences per fired flag — use as evidence. */
  evidence_sentences: Partial<Record<ForensicFlag, string[]>>;
}

export type TrendDirection = "up" | "down" | "flat";

export interface TrajectoryPoint {
  /** ISO date string, e.g. "2023-11-03". */
  filing_date: string;
  /** "10-K" | "20-F" | "40-F". */
  form: string;
  risk: number;
  business_model: number;
  moat: number;
}

export interface Trend {
  /** Signed delta of the latest point vs. the prior one. */
  change: number;
  direction: TrendDirection;
}

/**
 * Multi-year trend of the text-based scores. Only risk / business_model / moat
 * have a trajectory (financials and geopolitics intentionally do not).
 */
export interface ScoreTrajectory {
  /** Oldest -> newest. */
  points: TrajectoryPoint[];
  filings_compared: number;
  /** Empty when < 2 filings compared. */
  trends: {
    risk?: Trend;
    business_model?: Trend;
    moat?: Trend;
  };
}

/** The five rule-based meters (0–100). */
export interface Scores {
  financial: number;
  risk: number;
  business_model: number;
  moat: number;
  geopolitical: number;
}

/** The LLM narrative block (unchanged by the T4 work). Null if no LLM configured. */
export interface LLMAnalysis {
  enhanced_summary: string;
  investment_thesis: string;
  key_risks: string[];
  key_strengths: string[];
  score_commentary: string;
  red_flags: string[];
}

export interface AnalyzeResponse {
  cik: string;
  company_name: string;
  ticker: string;
  overall_score: number;

  // --- T4 additions (all optional / defensive) ---
  confidence?: Confidence;
  forensic?: Forensic;
  score_trajectory?: ScoreTrajectory;
  /** Plain-English notes on internal tensions; display-ready sentences. Empty when coherent. */
  contradictions?: string[];

  scores: Scores;
  summary: string;
  strengths: string[];
  weaknesses: string[];
  recent_changes: string[];

  /** Each scorer's full output + change_detection; mostly for power users/debug. */
  details: Record<string, unknown>;
  financial_snapshot: Record<string, unknown>;
  llm_analysis: LLMAnalysis | null;
}

# Frontend migration — T4 `/analyze` response additions

The backend `POST /analyze` endpoint gained four new top-level response fields
(the "T4" features). The endpoint path, request body (`{company_name, ticker?}`),
and all pre-existing response fields are **unchanged** — these additions are
purely additive. All four may be absent/empty on older or data-thin responses,
so render defensively.

| Field | Type | Purpose | UI suggestion |
|---|---|---|---|
| `confidence` | `{score, level, factors}` | How much real data backs the analysis | Badge near overall score, colored by `level` (high/moderate/low) |
| `forensic` | `{flags, evidence_sentences, ...}` | Accounting/disclosure red flags, **not** in `overall_score` | Separate warning section, one chip per fired flag + evidence on expand |
| `score_trajectory` | `{points, trends, filings_compared}` | Multi-year trend of risk/business_model/moat | Sparkline/line chart + per-dimension direction summary |
| `contradictions` | `string[]` | Internal tensions; display-ready sentences | Caution callout; hide when empty |

Files in this folder:

- **`analyze-response.types.ts`** — annotated TypeScript interfaces for the full
  response. Copy/adapt into the frontend repo.
- **`analyze-response.sample.json`** — a representative full response payload to
  develop/test against.

## Deployment note (not a code change)

The backend's CORS allowlist is now env-driven via `CORS_ALLOW_ORIGINS`
(defaults to `*` for dev). In any non-dev environment, that variable must
include the frontend's origin or browser requests will be blocked.

## Ready-to-paste prompt for the frontend repo

> The `sec_analyzer` backend `/analyze` endpoint now returns four new top-level
> fields in addition to everything it already returned. The request body
> (`{company_name, ticker?}`), the endpoint path, and all pre-existing response
> fields (`overall_score`, `scores`, `summary`, `strengths`, `weaknesses`,
> `recent_changes`, `details`, `financial_snapshot`, `llm_analysis`, etc.) are
> **unchanged** — these additions are purely additive, so nothing existing
> should break. Add UI to surface the four new blocks. They may be absent or
> empty on older/thin responses, so render defensively (treat missing/empty as
> "not available"). The exact shapes and a sample payload are in the backend
> repo at `docs/analyze-response.types.ts` and `docs/analyze-response.sample.json`.
>
> 1. **`confidence`** — `{score: 0-100, level: "high"|"moderate"|"low", factors: {...}}`.
>    Display near the overall score as a badge colored by level (high=green,
>    moderate=amber, low=red), e.g. "Confidence: High (80/100)". Expose `factors`
>    in a tooltip. When `level` is `low`, make it visually obvious — the field
>    exists to stop a thin analysis being read as a strong one.
> 2. **`forensic`** — `{total_forensic_score, flags: string[], evidence_sentences: {flag: string[]}, ...}`.
>    These are deliberately NOT in `overall_score` — render as discrete warnings.
>    Flag values: `going_concern`, `restatement`, `material_weakness`,
>    `impairment`, `related_party`, `liquidity_covenant`, `sec_investigation`,
>    `auditor_change`. One warning chip per fired flag with a human-readable label
>    and its `evidence_sentences[flag]` (quoted filing sentences) on expand. Show
>    a quiet "no red flags detected" state when `flags` is empty.
> 3. **`score_trajectory`** — `{points: [{filing_date, form, risk, business_model, moat}], filings_compared, trends: {dim: {change, direction}}}`.
>    `points` is oldest→newest. Render a small multi-line/sparkline chart of risk,
>    business_model, moat over `filing_date`, plus a `trends` summary (per dimension:
>    direction up/down/flat + signed change, e.g. "Risk ↑ +5"). Only these three
>    scores have a trajectory. Show "Not enough annual filings for a trend" when
>    `filings_compared < 2` or `trends` is empty.
> 4. **`contradictions`** — `string[]` of plain-English notes flagging internal
>    tensions (each is a complete, display-ready sentence). Render as a caution
>    callout ("Tensions to weigh") when non-empty; hide the section when empty.
>
> Update the TypeScript types/interfaces for the `/analyze` payload to include
> these four fields (all optional). No changes to API calls, request bodies, or
> auth are needed.

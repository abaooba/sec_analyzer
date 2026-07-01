"""Rank the screen cross-sectionally and raise the risk flags.

A single company's Piotroski or ROIC number means little in isolation — the point
of a screen is *relative* standing. This module turns each raw metric into a
0-100 percentile rank within the universe, blends those into a **quality** axis
(F-Score + ROIC + low accruals) and a **value** axis (FCF yield), and ranks the
names by their combined standing. It also fires the two flags the brief calls for:
distress (a low Altman Z) and earnings-quality risk (high accruals).

Everything here is pure: it takes the list of metric bundles from `metrics.py`
and returns an enriched, sorted structure. No I/O, so ranking is unit-tested with
hand-built rows.
"""

from .metrics import ACCRUALS_RISK_THRESHOLD

# Metrics ranked "higher is better". Accruals is handled separately because for
# it lower is better (we invert its percentile into the quality axis).
_HIGHER_IS_BETTER = ("f_score", "roic", "fcf_yield", "altman_z")

# A company is an earnings-quality concern if its accruals sit in the worst
# quartile of a big-enough peer group (percentile >= this), independent of the
# absolute ACCRUALS_RISK_THRESHOLD.
_ACCRUALS_WORST_QUARTILE = 75.0
_MIN_UNIVERSE_FOR_QUARTILE = 4


def _percentile_ranks(indexed_values: list[tuple[int, float | None]]) -> dict[int, float]:
    """Min-max rank percentiles (0-100) for the non-None values, keyed by row index.

    The best value in the universe maps to 100 and the worst to 0, so the metric
    spans the full range — markers spread across the whole scatter instead of
    bunching in the middle. Ties share the average of their ordinal positions
    (position = #strictly-below + (#equal-1)/2, normalized by n-1). A lone value
    has no cross-section, so it gets a neutral 50.
    """
    present = [(i, v) for i, v in indexed_values if v is not None]
    n = len(present)
    ranks: dict[int, float] = {}
    if n == 1:
        ranks[present[0][0]] = 50.0
        return ranks
    for i, v in present:
        below = sum(1 for _, w in present if w < v)
        equal = sum(1 for _, w in present if w == v)
        position = below + (equal - 1) / 2  # averaged ordinal position, 0..n-1
        ranks[i] = round(position / (n - 1) * 100, 1)
    return ranks


def _mean(values: list[float | None]) -> float | None:
    """Arithmetic mean of the non-None values, or None if there are none."""
    present = [v for v in values if v is not None]
    if not present:
        return None
    return round(sum(present) / len(present), 1)


def _median(values: list[float | None]) -> float | None:
    """Median of the non-None values (used for the scatter's quadrant lines)."""
    present = sorted(v for v in values if v is not None)
    n = len(present)
    if n == 0:
        return None
    mid = n // 2
    if n % 2:
        return round(present[mid], 1)
    return round((present[mid - 1] + present[mid]) / 2, 1)


def rank_screen(metrics_list: list[dict]) -> dict:
    """Enrich each company with percentiles, composites, and flags, then rank.

    Returns {"rows": [...sorted best-first...], "universe_size", "medians", ...}.
    Each row carries `percentiles`, `quality_score`, `value_score`,
    `composite_score`, `flags`, and a 1-based `rank`.
    """
    rows = [dict(m) for m in metrics_list]  # shallow copy; we annotate in place
    universe_size = len(rows)

    # 1. Percentile-rank every ranked column across the universe.
    percentiles: dict[str, dict[int, float]] = {}
    for metric in (*_HIGHER_IS_BETTER, "accruals"):
        column = [(i, row.get(metric)) for i, row in enumerate(rows)]
        percentiles[metric] = _percentile_ranks(column)

    # 2. Compose quality + value axes and attach per-row percentiles.
    for i, row in enumerate(rows):
        pcts = {
            "f_score": percentiles["f_score"].get(i),
            "roic": percentiles["roic"].get(i),
            "accruals": percentiles["accruals"].get(i),
            "fcf_yield": percentiles["fcf_yield"].get(i),
            "altman_z": percentiles["altman_z"].get(i),
        }
        row["percentiles"] = pcts

        # Quality = F-Score + ROIC + *low* accruals (invert the accruals percentile,
        # where a high percentile means high — bad — accruals).
        accruals_quality = None if pcts["accruals"] is None else 100 - pcts["accruals"]
        row["quality_score"] = _mean([pcts["f_score"], pcts["roic"], accruals_quality])

        # Value = cheapness, i.e. FCF yield percentile.
        row["value_score"] = pcts["fcf_yield"]

        # Overall standing = equal-weight blend of the two axes (whichever exist).
        row["composite_score"] = _mean([row["quality_score"], row["value_score"]])

    # 3. Fire the flags.
    for i, row in enumerate(rows):
        flags: list[str] = []
        if row.get("distress_zone") == "distress":
            flags.append("distress")

        accruals = row.get("accruals")
        accruals_pct = row["percentiles"]["accruals"]
        worst_quartile = (
            universe_size >= _MIN_UNIVERSE_FOR_QUARTILE
            and accruals_pct is not None
            and accruals_pct >= _ACCRUALS_WORST_QUARTILE
        )
        if accruals is not None and (accruals >= ACCRUALS_RISK_THRESHOLD or worst_quartile):
            flags.append("earnings_quality_risk")

        row["flags"] = flags

    # 4. Sort best-first. Rows with no composite (too little data to place) sink to
    # the bottom but keep a stable order by F-Score then ticker.
    def sort_key(row: dict):
        composite = row.get("composite_score")
        has_composite = composite is not None
        return (
            has_composite,
            composite if has_composite else 0,
            row.get("f_score") or 0,
            row.get("ticker") or "",
        )

    rows.sort(key=sort_key, reverse=True)
    for rank, row in enumerate(rows, start=1):
        row["rank"] = rank

    medians = {
        "value_score": _median([row["value_score"] for row in rows]),
        "quality_score": _median([row["quality_score"] for row in rows]),
    }

    return {
        "universe_size": universe_size,
        "rows": rows,
        "medians": medians,
        "flag_counts": {
            "distress": sum(1 for r in rows if "distress" in r["flags"]),
            "earnings_quality_risk": sum(1 for r in rows if "earnings_quality_risk" in r["flags"]),
        },
    }

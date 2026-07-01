"""Tests for cross-sectional ranking: percentiles, quality/value composites, the
distress + earnings-quality flags, and best-first ordering."""

from backend.app.screening.ranking import rank_screen


def row(ticker, **kw):
    """A minimal metric bundle with sensible neutral defaults."""
    base = dict(
        ticker=ticker, name=ticker, cik=ticker,
        f_score=5, altman_z=3.0, distress_zone="safe", accruals=0.0,
        roic=0.10, fcf_yield=0.03, earnings_yield=0.03,
    )
    base.update(kw)
    return base


def test_percentiles_and_ordering_best_first():
    rows = [
        row("HI", f_score=9, roic=0.30, fcf_yield=0.08, accruals=-0.05),
        row("MID", f_score=5, roic=0.10, fcf_yield=0.03, accruals=0.0),
        row("LO", f_score=1, roic=-0.05, fcf_yield=0.005, accruals=0.05),
    ]
    result = rank_screen(rows)
    by_ticker = {r["ticker"]: r for r in result["rows"]}

    # Top of every "higher is better" metric -> 100th percentile.
    assert by_ticker["HI"]["percentiles"]["f_score"] == 100.0
    assert by_ticker["LO"]["percentiles"]["f_score"] == 0.0
    # Quality inverts accruals (low accruals is good), so HI leads on quality too.
    assert by_ticker["HI"]["quality_score"] > by_ticker["LO"]["quality_score"]

    # Best composite ranked #1.
    assert result["rows"][0]["ticker"] == "HI"
    assert result["rows"][0]["rank"] == 1
    assert result["rows"][-1]["ticker"] == "LO"


def test_distress_flag_from_zone():
    rows = [row("A"), row("B", distress_zone="distress", altman_z=1.0)]
    result = rank_screen(rows)
    flags = {r["ticker"]: r["flags"] for r in result["rows"]}
    assert "distress" in flags["B"]
    assert "distress" not in flags["A"]
    assert result["flag_counts"]["distress"] == 1


def test_earnings_quality_flag_from_absolute_threshold():
    # Only two names (below the quartile-size floor), so the flag must come from
    # the absolute accruals threshold (>= 0.10), not the cross-sectional quartile.
    rows = [row("CLEAN", accruals=0.01), row("DIRTY", accruals=0.20)]
    result = rank_screen(rows)
    flags = {r["ticker"]: r["flags"] for r in result["rows"]}
    assert "earnings_quality_risk" in flags["DIRTY"]
    assert "earnings_quality_risk" not in flags["CLEAN"]


def test_earnings_quality_flag_from_worst_quartile():
    # Four names, all below the absolute threshold, so only the cross-sectional
    # worst-quartile rule can fire — and it should, for the highest-accruals name.
    rows = [
        row("A", accruals=0.00),
        row("B", accruals=0.02),
        row("C", accruals=0.04),
        row("D", accruals=0.08),  # highest accruals, still < 0.10 absolute
    ]
    result = rank_screen(rows)
    flags = {r["ticker"]: r["flags"] for r in result["rows"]}
    assert "earnings_quality_risk" in flags["D"]
    assert flags["A"] == []


def test_missing_composite_rows_sink_to_bottom():
    # A row with no rankable value axis / quality inputs still gets placed, last.
    rows = [
        row("GOOD", f_score=8, roic=0.25, fcf_yield=0.07, accruals=-0.02),
        row("SPARSE", f_score=None, roic=None, fcf_yield=None, accruals=None,
            altman_z=None, distress_zone="unknown"),
    ]
    result = rank_screen(rows)
    assert result["rows"][0]["ticker"] == "GOOD"
    assert result["rows"][-1]["ticker"] == "SPARSE"
    assert result["rows"][-1]["composite_score"] is None


def test_medians_reported_for_scatter_quadrants():
    rows = [
        row("A", f_score=9, roic=0.30, fcf_yield=0.08, accruals=-0.05),
        row("B", f_score=5, roic=0.10, fcf_yield=0.03),
        row("C", f_score=1, roic=-0.05, fcf_yield=0.005, accruals=0.05),
    ]
    result = rank_screen(rows)
    assert result["medians"]["value_score"] is not None
    assert result["medians"]["quality_score"] is not None

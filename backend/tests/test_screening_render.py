"""Tests for screen presentation: color bands, the ANSI/plain table, the ASCII
scatter, and the structured scatter points. The matplotlib PNG path is exercised
only when the library is installed (importorskip)."""

import pytest

from backend.app.screening.ranking import rank_screen
from backend.app.screening.render import (
    metric_color,
    render_scatter_ascii,
    render_scatter_png,
    render_screen_table,
    row_colors,
    scatter_points,
)


def _ranked():
    rows = [
        dict(ticker="HI", cik="1", f_score=9, altman_z=6.0, distress_zone="safe",
             accruals=-0.05, roic=0.30, fcf_yield=0.08, earnings_yield=0.05),
        dict(ticker="LO", cik="2", f_score=2, altman_z=0.9, distress_zone="distress",
             accruals=0.20, roic=-0.05, fcf_yield=0.005, earnings_yield=0.0),
    ]
    return rank_screen(rows)


# --- color bands -----------------------------------------------------------

def test_metric_color_bands():
    assert metric_color("f_score", 8) == "green"
    assert metric_color("f_score", 5) == "amber"
    assert metric_color("f_score", 2) == "red"
    assert metric_color("roic", 0.20) == "green"
    assert metric_color("fcf_yield", 0.06) == "green"
    assert metric_color("accruals", -0.01) == "green"  # negative accruals = good
    assert metric_color("accruals", 0.20) == "red"
    assert metric_color("f_score", None) == "neutral"


def test_altman_color_reads_zone_not_raw_score():
    assert metric_color("altman_z", 1.0, {"distress_zone": "distress"}) == "red"
    assert metric_color("altman_z", 3.0, {"distress_zone": "safe"}) == "green"
    assert metric_color("altman_z", 2.0, {"distress_zone": "grey"}) == "amber"


def test_row_colors_covers_all_metrics():
    colors = row_colors({"f_score": 9, "altman_z": 6.0, "distress_zone": "safe",
                         "accruals": -0.05, "roic": 0.30, "fcf_yield": 0.08})
    assert colors == {"f_score": "green", "altman_z": "green", "accruals": "green",
                      "roic": "green", "fcf_yield": "green"}


# --- table -----------------------------------------------------------------

def test_table_plain_has_no_ansi_and_lists_tickers():
    text = render_screen_table(_ranked(), use_color=False)
    assert "\033[" not in text  # no ANSI escapes in plain mode
    assert "HI" in text and "LO" in text
    assert "CROSS-SECTIONAL SCREEN" in text
    assert "distress" in text  # LO's zone


def test_table_color_mode_emits_ansi():
    text = render_screen_table(_ranked(), use_color=True)
    assert "\033[" in text


# --- scatter ---------------------------------------------------------------

def test_ascii_scatter_places_markers_and_axes():
    text = render_scatter_ascii(_ranked(), use_color=False)
    assert "VALUE vs QUALITY" in text
    assert "┼" in text  # quadrant crosshair
    assert "H" in text and "L" in text  # first-letter markers for HI / LO


def test_scatter_points_structure_and_color():
    points = scatter_points(_ranked())
    assert {p["ticker"] for p in points} == {"HI", "LO"}
    lo = next(p for p in points if p["ticker"] == "LO")
    assert lo["color"] == "red"  # distress
    assert set(lo) == {"ticker", "value", "quality", "color", "flags"}


def test_scatter_points_skips_rows_missing_an_axis():
    rows = [dict(ticker="X", cik="1", f_score=None, altman_z=None, distress_zone="unknown",
                 accruals=None, roic=None, fcf_yield=None, earnings_yield=None)]
    assert scatter_points(rank_screen(rows)) == []


def test_scatter_png_none_when_no_points(tmp_path):
    empty = rank_screen([])
    assert render_scatter_png(empty, str(tmp_path / "x.png")) is None


def test_scatter_png_written_when_matplotlib_available(tmp_path):
    pytest.importorskip("matplotlib")
    out = tmp_path / "scatter.png"
    result = render_scatter_png(_ranked(), str(out))
    assert result == str(out)
    assert out.exists() and out.stat().st_size > 0

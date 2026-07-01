"""Presentation for the screen: a color-coded table and a value-vs-quality scatter.

Two audiences, one set of thresholds:
  - the CLI gets an ANSI color table and an ASCII scatter (always available, no
    plotting dependency), plus an optional matplotlib PNG when the library is
    installed;
  - the API gets machine-readable *color names* (via `row_colors`) so the
    frontend can paint the same red/amber/green without re-deriving the bands.

`metric_color` is the single source of truth for what counts as good/ok/bad on
each metric, so the terminal and the browser always agree.
"""

import logging

logger = logging.getLogger(__name__)

# ANSI escapes for the terminal. Kept tiny and local; color is opt-in per call so
# piped/non-tty output (and tests) can render the exact same layout without codes.
_ANSI = {
    "green": "\033[32m",
    "amber": "\033[33m",
    "red": "\033[31m",
    "neutral": "\033[2m",   # dim
    "reset": "\033[0m",
    "bold": "\033[1m",
}

# Unicode markers used in the scatter and as flag glyphs in the table.
_FLAG_GLYPH = {"distress": "D", "earnings_quality_risk": "A"}


def metric_color(metric: str, value, row: dict | None = None) -> str:
    """Classify a metric value as 'green' / 'amber' / 'red' / 'neutral'.

    Bands are absolute (not cross-sectional) so a cell's color means the same
    thing on every screen. `altman_z` reads the precomputed distress zone off the
    row rather than the raw score, since the safe/grey/distress cut points depend
    on which Altman model was used.
    """
    if metric == "altman_z":
        zone = (row or {}).get("distress_zone") or ""
        return {"safe": "green", "grey": "amber", "distress": "red"}.get(zone, "neutral")

    if value is None:
        return "neutral"

    if metric == "f_score":
        return "green" if value >= 7 else "amber" if value >= 4 else "red"
    if metric == "roic":
        return "green" if value >= 0.15 else "amber" if value >= 0.05 else "red"
    if metric == "fcf_yield":
        return "green" if value >= 0.05 else "amber" if value >= 0.02 else "red"
    if metric == "accruals":
        # Lower is better; negative accruals (cash > earnings) are ideal.
        return "green" if value <= 0.02 else "amber" if value <= 0.10 else "red"
    return "neutral"


def row_colors(row: dict) -> dict[str, str]:
    """Per-metric color names for one row — the API's coloring hook for the UI."""
    return {
        metric: metric_color(metric, row.get(metric), row)
        for metric in ("f_score", "altman_z", "accruals", "roic", "fcf_yield")
    }


def _paint(text: str, color: str, use_color: bool) -> str:
    """Wrap `text` in an ANSI color (or return it untouched when color is off)."""
    if not use_color or color not in _ANSI:
        return text
    return f"{_ANSI[color]}{text}{_ANSI['reset']}"


def _fmt_pct(value, digits: int = 1) -> str:
    """Format a fraction as a percentage string, or '—' when missing."""
    return "—" if value is None else f"{value * 100:.{digits}f}%"


def _fmt_num(value, digits: int = 2) -> str:
    """Format a number, or '—' when missing."""
    return "—" if value is None else f"{value:.{digits}f}"


def _fmt_score(value) -> str:
    """Format a 0-100 composite/percentile as an integer, or '—'."""
    return "—" if value is None else f"{value:.0f}"


def _flags_text(flags: list[str]) -> str:
    """Compact flag glyphs, e.g. '⚠D A' — empty string when clean."""
    if not flags:
        return ""
    return "⚠" + "".join(_FLAG_GLYPH.get(f, "?") for f in flags)


def render_screen_table(ranked: dict, use_color: bool = True) -> str:
    """Render the ranked screen as a fixed-width, color-coded table.

    Columns: rank, ticker, Piotroski F (x/9), Altman Z + zone, accruals %, ROIC %,
    FCF yield %, and the quality / value / composite percentile scores, plus a
    flags column. Metric cells are individually colored via `metric_color`.
    """
    rows = ranked.get("rows", [])

    header = ["#", "Ticker", "F", "AltZ", "Zone", "Accr", "ROIC", "FCFy", "Qual", "Val", "Comp", "Flags"]
    widths = [3, 8, 4, 7, 8, 7, 7, 7, 5, 5, 5, 7]
    aligns = ["r", "l", "r", "r", "l", "r", "r", "r", "r", "r", "r", "l"]

    def line(cells: list[str], colors: list[str | None]) -> str:
        out = []
        for text, width, align, color in zip(cells, widths, aligns, colors):
            text = text[:width]
            padded = text.rjust(width) if align == "r" else text.ljust(width)
            out.append(_paint(padded, color, use_color) if color else padded)
        return "  ".join(out)

    title = f"CROSS-SECTIONAL SCREEN — {ranked.get('universe_size', len(rows))} companies"
    body = [
        _paint(title, "bold", use_color),
        line(header, [None] * len(header)),
        "  ".join("-" * w for w in widths),
    ]

    for row in rows:
        f_avail = row.get("f_score_available")
        f_text = "—" if row.get("f_score") is None else f"{row['f_score']}/9" if f_avail == 9 else f"{row['f_score']}*"
        cells = [
            str(row.get("rank", "")),
            row.get("ticker", "") or row.get("cik", ""),
            f_text,
            _fmt_num(row.get("altman_z")),
            (row.get("distress_zone") or "—"),
            _fmt_pct(row.get("accruals")),
            _fmt_pct(row.get("roic")),
            _fmt_pct(row.get("fcf_yield")),
            _fmt_score(row.get("quality_score")),
            _fmt_score(row.get("value_score")),
            _fmt_score(row.get("composite_score")),
            _flags_text(row.get("flags", [])),
        ]
        colors = [
            None,
            None,
            metric_color("f_score", row.get("f_score")),
            metric_color("altman_z", row.get("altman_z"), row),
            metric_color("altman_z", row.get("altman_z"), row),
            metric_color("accruals", row.get("accruals")),
            metric_color("roic", row.get("roic")),
            metric_color("fcf_yield", row.get("fcf_yield")),
            None,
            None,
            None,
            "red" if row.get("flags") else None,
        ]
        body.append(line(cells, colors))

    # Footer: legend + Altman model note + flag tally.
    counts = ranked.get("flag_counts", {})
    body.append("")
    body.append(
        _paint("Flags:", "bold", use_color)
        + f"  ⚠D = distress (low Altman Z), {counts.get('distress', 0)} flagged"
        + f"   ⚠A = earnings-quality risk (high accruals), {counts.get('earnings_quality_risk', 0)} flagged"
    )
    body.append(
        _paint("Legend:", "bold", use_color)
        + "  F = Piotroski F-Score (x/9; * = partial data)   Qual/Val/Comp = 0-100 percentile."
        + "  Accr lower = better."
    )
    return "\n".join(body)


def render_scatter_ascii(ranked: dict, width: int = 56, height: int = 18, use_color: bool = True) -> str:
    """Plot value (x, FCF-yield percentile) against quality (y) as an ASCII grid.

    Each company is a marker (its ticker's first letter) placed by its value and
    quality percentiles; markers are colored by flag. Crosshairs at the 50th
    percentile split the plane into quadrants — the top-right ("cheap & high
    quality") is the screen's sweet spot. Names missing either axis can't be
    placed and are listed underneath.
    """
    rows = ranked.get("rows", [])

    grid = [[" " for _ in range(width)] for _ in range(height)]
    colors = [[None for _ in range(width)] for _ in range(height)]

    mid_col = width // 2
    mid_row = height // 2
    # Draw the quadrant crosshairs first so markers overwrite them.
    for r in range(height):
        grid[r][mid_col] = "│"
    for c in range(width):
        grid[mid_row][c] = "─"
    grid[mid_row][mid_col] = "┼"

    plotted = 0
    not_plotted: list[str] = []
    for row in rows:
        x = row.get("value_score")
        y = row.get("quality_score")
        label = (row.get("ticker") or row.get("cik") or "?")[:1].upper()
        if x is None or y is None:
            not_plotted.append(row.get("ticker") or row.get("cik") or "?")
            continue
        col = min(width - 1, max(0, round(x / 100 * (width - 1))))
        # Invert y: high quality at the top of the grid.
        r = min(height - 1, max(0, round((100 - y) / 100 * (height - 1))))
        # A cell already holding a different marker becomes '#'.
        existing = grid[r][col]
        grid[r][col] = label if existing in (" ", "│", "─", "┼") else "#"
        flags = row.get("flags", [])
        colors[r][col] = "red" if "distress" in flags else "amber" if flags else "green"
        plotted += 1

    lines = [_paint("VALUE vs QUALITY", "bold", use_color) + "   (↑ higher quality, → cheaper / higher FCF yield)"]
    for r in range(height):
        rendered = "".join(
            _paint(grid[r][c], colors[r][c], use_color) if colors[r][c] else grid[r][c]
            for c in range(width)
        )
        lines.append(rendered)
    lines.append("Low value" + " " * max(1, width - 18) + "High value")
    lines.append(
        "Top-right quadrant = cheap & high-quality (sweet spot); "
        "bottom-left = expensive & low-quality."
    )
    if not_plotted:
        lines.append(f"Not plotted (missing value or quality): {', '.join(not_plotted)}")
    return "\n".join(lines)


def scatter_points(ranked: dict) -> list[dict]:
    """Machine-readable scatter points for the API/frontend to plot.

    One entry per company that has both axes: {ticker, value, quality, color,
    flags}. `color` follows the flag convention (red distress / amber risk /
    green clean) so the browser chart matches the ASCII one.
    """
    points = []
    for row in ranked.get("rows", []):
        x = row.get("value_score")
        y = row.get("quality_score")
        if x is None or y is None:
            continue
        flags = row.get("flags", [])
        points.append(
            {
                "ticker": row.get("ticker") or row.get("cik"),
                "value": x,
                "quality": y,
                "color": "red" if "distress" in flags else "amber" if flags else "green",
                "flags": flags,
            }
        )
    return points


def render_scatter_png(ranked: dict, path: str) -> str | None:
    """Write a value-vs-quality scatter PNG to `path`, or None if matplotlib is absent.

    Lazily imports matplotlib with the headless Agg backend (so it works on a
    server with no display) — the CLI calls this as a bonus over the always-on
    ASCII scatter, and it's a no-op when the plotting stack isn't installed.
    """
    points = scatter_points(ranked)
    if not points:
        return None

    try:
        import matplotlib
        matplotlib.use("Agg")  # headless: no display needed
        import matplotlib.pyplot as plt
    except ImportError:
        logger.info("matplotlib not installed; skipping PNG scatter (ASCII scatter still rendered).")
        return None

    fill = {"red": "#d62728", "amber": "#ff7f0e", "green": "#2ca02c"}
    fig, ax = plt.subplots(figsize=(8, 6))
    for point in points:
        ax.scatter(point["value"], point["quality"], c=fill.get(point["color"], "#1f77b4"), s=90, edgecolors="black", linewidths=0.5, zorder=3)
        ax.annotate(point["ticker"], (point["value"], point["quality"]), xytext=(4, 4), textcoords="offset points", fontsize=8)

    ax.axvline(50, color="grey", linewidth=0.8, linestyle="--")
    ax.axhline(50, color="grey", linewidth=0.8, linestyle="--")
    ax.set_xlim(-2, 102)
    ax.set_ylim(-2, 102)
    ax.set_xlabel("Value  →  (FCF-yield percentile, cheaper = right)")
    ax.set_ylabel("Quality  →  (F-Score / ROIC / low accruals)")
    ax.set_title(f"Value vs Quality — {ranked.get('universe_size', len(points))} companies")
    ax.text(75, 96, "cheap & high-quality", color="grey", fontsize=8, ha="center")
    fig.tight_layout()
    fig.savefig(path, dpi=120)
    plt.close(fig)
    return path

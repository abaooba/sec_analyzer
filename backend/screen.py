"""CLI entry point for the cross-sectional screen.

Run with:
    python -m backend.screen AAPL MSFT NVDA GOOGL
    python -m backend.screen            # then type a comma-separated list

Resolves the tickers, ingests each company's XBRL facts, computes the Piotroski /
Altman Z / accruals / ROIC / FCF-yield battery, ranks the universe, and prints a
color-coded screen table plus an ASCII value-vs-quality scatter. When matplotlib
is installed it also drops a PNG of the scatter next to the DB and prints its path.

The sys.path shim mirrors main.py so this runs both as a module (`-m backend.screen`)
and as a loose script.
"""

import logging
import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.app.config import REPO_ROOT
from backend.app.db import init_db
from backend.app.screening.render import (
    render_scatter_ascii,
    render_scatter_png,
    render_screen_table,
)
from backend.app.screening.service import run_screen


def _read_tickers(argv: list[str]) -> list[str]:
    """Tickers from argv (space-separated), else an interactive comma-list prompt."""
    if argv:
        return argv
    raw = input("Enter tickers (comma or space separated): ").strip()
    return [part for chunk in raw.split(",") for part in chunk.split()]


def main():
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    tickers = _read_tickers(sys.argv[1:])
    if not tickers:
        print("No tickers entered.")
        return

    init_db()
    result = run_screen(tickers)

    if not result["rows"]:
        print("\nNothing to screen — no company had usable annual fundamentals.")
        if result["unresolved"]:
            print(f"Unresolved tickers: {', '.join(result['unresolved'])}")
        if result["no_data"]:
            print(f"No fundamentals: {', '.join(result['no_data'])}")
        return

    print("\n" + "=" * 72)
    print(render_screen_table(result))
    print("\n" + "=" * 72)
    print(render_scatter_ascii(result))

    # Surface any names that couldn't be screened, so gaps are explicit.
    if result["unresolved"]:
        print(f"\nUnresolved tickers (skipped): {', '.join(result['unresolved'])}")
    if result["no_data"]:
        print(f"No annual fundamentals (skipped): {', '.join(result['no_data'])}")

    # Bonus PNG scatter when matplotlib is available (no-op otherwise).
    png_path = str(REPO_ROOT / "data" / "screen_value_vs_quality.png")
    written = render_scatter_png(result, png_path)
    if written:
        print(f"\nScatter chart written to: {written}")


if __name__ == "__main__":
    main()

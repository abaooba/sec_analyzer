"""Load externalized scorer config (keywords / weights / caps) from keywords.toml.

The keyword regex lists, category weights, and score caps for the keyword-based
scorers (risk, moat, business_model, geopolitics) live in `keywords.toml` so they
can be tuned or generalized without touching scoring code. Regex patterns are
stored in TOML *literal* strings, so their backslashes need no escaping. The file
is read once, at import.
"""

import tomllib
from pathlib import Path

_CONFIG_PATH = Path(__file__).with_name("keywords.toml")

with _CONFIG_PATH.open("rb") as _f:
    _CONFIG = tomllib.load(_f)


def scorer_config(scorer: str) -> dict:
    """Return one scorer's config sub-table: its `keywords` (category -> list of
    regex pattern strings), `weights` (category -> float), and any cap scalars."""
    return _CONFIG[scorer]

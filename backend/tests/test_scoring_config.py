"""Tests for the externalized scoring config (keywords.toml + _keyword_config)."""

import re

from backend.app.scoring import _keyword_config, risk


def test_scorer_config_returns_expected_tables():
    cfg = _keyword_config.scorer_config("risk")
    assert {"keywords", "weights", "category_cap", "total_cap"} <= set(cfg)
    assert isinstance(cfg["keywords"], dict)
    assert isinstance(cfg["category_cap"], int)


def test_risk_keywords_and_weights_align():
    # Every keyword category must have a matching weight, and non-empty patterns.
    assert set(risk.RISK_KEYWORDS) == set(risk.RISK_WEIGHTS)
    for category, patterns in risk.RISK_KEYWORDS.items():
        assert patterns, f"{category} has no patterns"
        assert all(isinstance(p, str) for p in patterns)


def test_externalized_regex_patterns_compile():
    # The patterns came through TOML literal strings; make sure none got mangled
    # (a stray escaping bug would surface here as a regex compile error).
    for patterns in risk.RISK_KEYWORDS.values():
        for pattern in patterns:
            re.compile(pattern)

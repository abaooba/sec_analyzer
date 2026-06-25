"""Tests for the LLM analysis layer's retry / fallback orchestration.

No network or real Groq client is used: the Groq constructor is stubbed and
`_request_analysis` (the single call+parse+validate step) is replaced with a
controllable fake, so these exercise only the bounded-retry-then-degrade logic.
"""

import logging

import pytest

from backend.app import llm_analysis
from backend.app.llm_analysis import LLMAnalysis


def _sample_analysis() -> LLMAnalysis:
    return LLMAnalysis(
        enhanced_summary="s",
        investment_thesis="t",
        key_risks=["r"],
        key_strengths=["k"],
        score_commentary="c",
        red_flags=[],
    )


@pytest.fixture(autouse=True)
def _no_sleep_and_fake_client(monkeypatch):
    """Never really sleep between retries, never build a real Groq client, and
    pretend a key is configured (so generate_llm_analysis gets past the guard)."""
    monkeypatch.setattr(llm_analysis.time, "sleep", lambda *a, **k: None)
    monkeypatch.setattr(llm_analysis, "Groq", lambda api_key: object())
    monkeypatch.setattr(llm_analysis.settings, "groq_api_key", "test-key")


def test_returns_none_without_api_key(monkeypatch):
    monkeypatch.setattr(llm_analysis.settings, "groq_api_key", "")
    calls = []
    monkeypatch.setattr(llm_analysis, "_request_analysis", lambda *a, **k: calls.append(1))
    result = llm_analysis.generate_llm_analysis("Acme", None, {}, {})
    assert result is None
    assert calls == []  # never even attempted


def test_succeeds_on_first_attempt(monkeypatch):
    calls = {"n": 0}

    def ok(client, user_message):
        calls["n"] += 1
        return _sample_analysis()

    monkeypatch.setattr(llm_analysis, "_request_analysis", ok)
    result = llm_analysis.generate_llm_analysis("Acme", None, {}, {})
    assert isinstance(result, LLMAnalysis)
    assert calls["n"] == 1  # no retry needed


def test_retries_then_succeeds(monkeypatch):
    calls = {"n": 0}

    def flaky(client, user_message):
        calls["n"] += 1
        if calls["n"] == 1:
            raise ValueError("bad JSON on first try")
        return _sample_analysis()

    monkeypatch.setattr(llm_analysis, "_request_analysis", flaky)
    result = llm_analysis.generate_llm_analysis("Acme", None, {}, {})
    assert isinstance(result, LLMAnalysis)
    assert calls["n"] == 2  # failed once, retried, then succeeded


def test_degrades_to_none_after_exhausting_retries(monkeypatch):
    calls = {"n": 0}

    def always_fail(client, user_message):
        calls["n"] += 1
        raise RuntimeError("persistent failure")

    monkeypatch.setattr(llm_analysis, "_request_analysis", always_fail)
    result = llm_analysis.generate_llm_analysis("Acme", None, {}, {})
    assert result is None
    assert calls["n"] == llm_analysis.LLM_MAX_ATTEMPTS  # tried exactly the cap


def test_logs_warning_after_exhausting_retries(monkeypatch, caplog):
    def always_fail(client, user_message):
        raise RuntimeError("persistent failure")

    monkeypatch.setattr(llm_analysis, "_request_analysis", always_fail)
    with caplog.at_level(logging.WARNING):
        result = llm_analysis.generate_llm_analysis("Acme", None, {}, {})

    assert result is None
    assert any("unavailable" in r.getMessage().lower() for r in caplog.records)


def test_build_forensic_block_lists_flags():
    from backend.app.llm_analysis import _build_forensic_block

    block = _build_forensic_block(
        {
            "flags": ["going_concern", "restatement"],
            "evidence_sentences": {"going_concern": ["substantial doubt exists"]},
        }
    )
    assert "GOING CONCERN" in block
    assert "substantial doubt exists" in block
    assert "RESTATEMENT" in block


def test_build_forensic_block_none():
    from backend.app.llm_analysis import _build_forensic_block

    assert _build_forensic_block({"flags": []}) == "None detected."
    assert _build_forensic_block({}) == "None detected."


def test_build_trajectory_block():
    from backend.app.llm_analysis import _build_trajectory_block

    block = _build_trajectory_block(
        {"filings_compared": 3, "trends": {"risk": {"change": 5.0, "direction": "up"}}}
    )
    assert "3 annual filings" in block
    assert "Risk: up" in block


def test_build_trajectory_block_insufficient():
    from backend.app.llm_analysis import _build_trajectory_block

    assert "Not enough" in _build_trajectory_block({"filings_compared": 1, "trends": {}})
    assert "Not enough" in _build_trajectory_block({})

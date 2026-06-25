"""Tests for the /analyze endpoint control flow (mocked pipeline, fully offline)."""

from fastapi.testclient import TestClient

from backend import api


def _patch_pipeline(monkeypatch, *, match, opinion=None):
    calls = {}
    monkeypatch.setattr(api, "init_db", lambda: calls.setdefault("init_db", True))
    monkeypatch.setattr(api, "find_company_match", lambda name, ticker=None: match)
    monkeypatch.setattr(api, "ingest_company", lambda cik: calls.setdefault("ingest", cik))
    monkeypatch.setattr(api, "ingest_company_facts", lambda cik: calls.setdefault("facts", cik))
    monkeypatch.setattr(api, "build_full_opinion", lambda cik, name, ticker: opinion)
    monkeypatch.setattr(
        api, "delete_local_filings_for_company", lambda cik: calls.setdefault("cleanup", cik)
    )
    return calls


def test_company_not_found_returns_error(monkeypatch):
    _patch_pipeline(monkeypatch, match=None)
    resp = TestClient(api.app).post("/analyze", json={"company_name": "Nope"})
    assert resp.status_code == 200
    assert resp.json() == {"error": "Could not find company: Nope"}


def test_success_returns_opinion_and_cleans_up(monkeypatch):
    opinion = {"overall_score": 73, "company_name": "Apple Inc."}
    calls = _patch_pipeline(
        monkeypatch,
        match={"cik": "0000320193", "company_name": "Apple Inc.", "ticker": "AAPL"},
        opinion=opinion,
    )
    resp = TestClient(api.app).post("/analyze", json={"company_name": "Apple", "ticker": "AAPL"})
    assert resp.status_code == 200
    assert resp.json() == opinion
    assert calls["ingest"] == "0000320193"
    assert calls["facts"] == "0000320193"
    assert calls["cleanup"] == "0000320193"  # the finally cleanup ran


def test_cleanup_runs_even_if_pipeline_raises(monkeypatch):
    calls = _patch_pipeline(
        monkeypatch, match={"cik": "1", "company_name": "C", "ticker": "T"}
    )

    def boom(cik, name, ticker):
        raise RuntimeError("pipeline failure")

    monkeypatch.setattr(api, "build_full_opinion", boom)

    resp = TestClient(api.app, raise_server_exceptions=False).post(
        "/analyze", json={"company_name": "C"}
    )
    assert resp.status_code == 500
    assert calls.get("cleanup") == "1"  # finally still ran despite the failure

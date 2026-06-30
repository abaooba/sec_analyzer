"""Tests for the /factor-attribution endpoint wiring (mocked service, offline).

The endpoint lazily imports `analyze_factor_exposure` from the service module, so
we patch it there and assert the request shaping (holdings vs. single ticker,
defaults, parameter forwarding) without running the real quant pipeline.
"""

from fastapi.testclient import TestClient

from backend import api


def _patch_service(monkeypatch):
    captured = {}

    def fake_analyze(holdings, start_date=None, end_date=None, rolling_window=126):
        captured["holdings"] = holdings
        captured["start_date"] = start_date
        captured["end_date"] = end_date
        captured["rolling_window"] = rolling_window
        return {"ok": True}

    monkeypatch.setattr(
        "backend.app.factors.service.analyze_factor_exposure", fake_analyze
    )
    return captured


def test_holdings_are_forwarded(monkeypatch):
    captured = _patch_service(monkeypatch)
    resp = TestClient(api.app).post(
        "/factor-attribution",
        json={"holdings": [{"ticker": "AAPL", "weight": 0.6}, {"ticker": "MSFT", "weight": 0.4}]},
    )
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}
    assert captured["holdings"] == [
        {"ticker": "AAPL", "weight": 0.6},
        {"ticker": "MSFT", "weight": 0.4},
    ]


def test_single_ticker_becomes_full_weight_holding(monkeypatch):
    captured = _patch_service(monkeypatch)
    resp = TestClient(api.app).post("/factor-attribution", json={"ticker": "SPY"})
    assert resp.status_code == 200
    assert captured["holdings"] == [{"ticker": "SPY", "weight": 1.0}]


def test_holding_weight_defaults_to_one(monkeypatch):
    captured = _patch_service(monkeypatch)
    TestClient(api.app).post(
        "/factor-attribution", json={"holdings": [{"ticker": "AAPL"}]}
    )
    assert captured["holdings"] == [{"ticker": "AAPL", "weight": 1.0}]


def test_dates_and_window_are_forwarded(monkeypatch):
    captured = _patch_service(monkeypatch)
    TestClient(api.app).post(
        "/factor-attribution",
        json={
            "ticker": "AAPL",
            "start_date": "2021-01-01",
            "end_date": "2023-12-31",
            "rolling_window": 90,
        },
    )
    assert captured["start_date"] == "2021-01-01"
    assert captured["end_date"] == "2023-12-31"
    assert captured["rolling_window"] == 90


def test_no_holdings_and_no_ticker_returns_error(monkeypatch):
    _patch_service(monkeypatch)
    resp = TestClient(api.app).post("/factor-attribution", json={})
    assert resp.status_code == 200
    assert "error" in resp.json()

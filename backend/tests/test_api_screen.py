"""Tests for the /screen endpoint control flow (mocked service, fully offline)."""

from fastapi.testclient import TestClient

from backend import api


def test_empty_tickers_returns_error(monkeypatch):
    monkeypatch.setattr(api, "init_db", lambda: None)
    resp = TestClient(api.app).post("/screen", json={"tickers": []})
    assert resp.status_code == 200
    assert resp.json() == {"error": "Provide a non-empty 'tickers' list."}


def test_screen_passes_flags_and_returns_service_result(monkeypatch):
    calls = {}
    monkeypatch.setattr(api, "init_db", lambda: calls.setdefault("init_db", True))

    fake_result = {"universe_size": 2, "rows": [], "scatter": {"points": []}}

    def fake_run_screen(tickers, *, ingest, fetch_market_caps):
        calls["args"] = (tickers, ingest, fetch_market_caps)
        return fake_result

    # The endpoint imports run_screen lazily from the service module, so patch it there.
    monkeypatch.setattr("backend.app.screening.service.run_screen", fake_run_screen)

    resp = TestClient(api.app).post(
        "/screen",
        json={"tickers": ["AAPL", "MSFT"], "ingest": False, "fetch_market_caps": False},
    )
    assert resp.status_code == 200
    assert resp.json() == fake_result
    assert calls["init_db"] is True
    assert calls["args"] == (["AAPL", "MSFT"], False, False)


def test_screen_defaults_ingest_and_market_caps_true(monkeypatch):
    calls = {}
    monkeypatch.setattr(api, "init_db", lambda: None)
    monkeypatch.setattr(
        "backend.app.screening.service.run_screen",
        lambda tickers, *, ingest, fetch_market_caps: calls.setdefault(
            "args", (tickers, ingest, fetch_market_caps)
        )
        or {"ok": True},
    )
    resp = TestClient(api.app).post("/screen", json={"tickers": ["AAPL"]})
    assert resp.status_code == 200
    assert calls["args"] == (["AAPL"], True, True)

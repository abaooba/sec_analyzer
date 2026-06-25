"""Tests for the shared httpx client factory and its consumers.

The factory tests verify the outbound-HTTP security posture without any network
call (a recorder stands in for httpx.Client). The routing tests verify that the
SEC/news clients actually build through the factory (a fake client stands in),
so the tls_verify policy reaches every outbound call.
"""

import pytest

from backend.app import company_lookup, http_client, sec_client


class _ClientRecorder:
    """Stands in for httpx.Client: records constructor kwargs, opens no socket."""

    last_kwargs: dict = {}

    def __init__(self, **kwargs):
        type(self).last_kwargs = kwargs


@pytest.fixture
def recorder(monkeypatch):
    monkeypatch.setattr(http_client.httpx, "Client", _ClientRecorder)
    return _ClientRecorder


def test_factory_defaults_to_secure_tls_verification(recorder, monkeypatch):
    monkeypatch.setattr(http_client.settings, "tls_verify", True)
    http_client.make_http_client(timeout=5.0)
    assert recorder.last_kwargs["verify"] is True
    assert recorder.last_kwargs["timeout"] == 5.0


def test_factory_honors_tls_verify_setting(recorder, monkeypatch):
    monkeypatch.setattr(http_client.settings, "tls_verify", False)
    http_client.make_http_client()
    assert recorder.last_kwargs["verify"] is False


def test_explicit_verify_kwarg_overrides_default(recorder, monkeypatch):
    monkeypatch.setattr(http_client.settings, "tls_verify", True)
    http_client.make_http_client(verify=False)
    assert recorder.last_kwargs["verify"] is False


def test_settings_tls_verify_defaults_true():
    """The shipped default must be secure (verification on)."""
    from backend.app.config import settings

    assert settings.tls_verify is True


# --- Routing: the SEC/news clients must go through make_http_client ------------

class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


class _FakeClient:
    """A context-manager httpx.Client stand-in that returns a fixed payload."""

    def __init__(self, payload, **kwargs):
        self._payload = payload
        self.kwargs = kwargs

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def get(self, url, **kwargs):
        return _FakeResponse(self._payload)


def _factory_returning(payload, captured):
    def factory(**kwargs):
        captured.update(kwargs)
        return _FakeClient(payload, **kwargs)

    return factory


def test_company_lookup_routes_through_factory(monkeypatch):
    captured: dict = {}
    payload = {"0": {"title": "Acme Inc", "ticker": "ACME", "cik_str": 123}}
    monkeypatch.setattr(company_lookup, "make_http_client", _factory_returning(payload, captured))
    assert company_lookup.load_company_tickers() == payload
    assert "headers" in captured  # built via the factory, not httpx directly


def test_sec_client_routes_through_factory(monkeypatch):
    captured: dict = {}
    payload = {"filings": "ok"}
    monkeypatch.setattr(sec_client, "make_http_client", _factory_returning(payload, captured))
    assert sec_client.SECClient().get_submissions("320193") == payload
    assert "headers" in captured

"""Tests for the shared httpx client factory.

These verify the outbound-HTTP security posture without making any network call:
a recorder stands in for httpx.Client and captures the kwargs the factory passes.
"""

import pytest

from backend.app import http_client


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

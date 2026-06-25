"""Tests for CORS configuration: the env parser and the API's CORS wiring."""

from fastapi.testclient import TestClient

from backend import api
from backend.app.config import _parse_csv_env


def test_parse_csv_env_single_wildcard():
    assert _parse_csv_env("*") == ["*"]


def test_parse_csv_env_multiple_with_whitespace():
    assert _parse_csv_env("https://a.com, https://b.com ") == [
        "https://a.com",
        "https://b.com",
    ]


def test_parse_csv_env_drops_blanks():
    assert _parse_csv_env("a,,b,") == ["a", "b"]
    assert _parse_csv_env("") == []


def test_api_allows_cross_origin_preflight_by_default():
    """With the default "*" config, a CORS preflight from any origin is allowed,
    handled by the middleware without invoking the /analyze pipeline."""
    client = TestClient(api.app)
    resp = client.options(
        "/analyze",
        headers={
            "Origin": "https://example.com",
            "Access-Control-Request-Method": "POST",
        },
    )
    assert resp.status_code == 200
    assert resp.headers["access-control-allow-origin"] == "*"

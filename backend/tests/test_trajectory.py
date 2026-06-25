"""Tests for the multi-year score trajectory (change_detection)."""

import types

from backend.app import change_detection as cd
from backend.app.change_detection import _trajectory_trends, build_score_trajectory


def _filing(date, form="10-K", path="p"):
    return types.SimpleNamespace(filing_date=date, form=form, local_path=path)


def test_trajectory_trends_direction():
    points = [
        {"risk": 10, "business_model": 50, "moat": 30},
        {"risk": 15, "business_model": 45, "moat": 30},
    ]
    trends = _trajectory_trends(points)
    assert trends["risk"] == {"change": 5, "direction": "up"}
    assert trends["business_model"] == {"change": -5, "direction": "down"}
    assert trends["moat"] == {"change": 0, "direction": "flat"}


def test_trajectory_trends_needs_two_points():
    assert _trajectory_trends([]) == {}
    assert _trajectory_trends([{"risk": 1, "business_model": 1, "moat": 1}]) == {}


def test_build_score_trajectory_orders_oldest_to_newest(monkeypatch):
    # Query returns newest-first; the trajectory should flip to oldest-first.
    monkeypatch.setattr(
        cd, "get_latest_annual_filings",
        lambda cik, limit=4: [_filing("2023-01-01"), _filing("2022-01-01")],
    )
    monkeypatch.setattr(
        cd, "extract_sections_from_filing",
        lambda filing: {
            "risk_factors": "tariffs and litigation and sanctions risk. " * 20,
            "business": "subscription services and recurring revenue platform. " * 20,
            "mdna": "",
            "full_text": "",
        },
    )
    result = build_score_trajectory("1", limit=4)
    assert result["filings_compared"] == 2
    assert [p["filing_date"] for p in result["points"]] == ["2022-01-01", "2023-01-01"]
    assert {"risk", "business_model", "moat"} <= set(result["points"][0])
    assert set(result["trends"]) == {"risk", "business_model", "moat"}


def test_build_score_trajectory_skips_unloadable_filings(monkeypatch):
    monkeypatch.setattr(
        cd, "get_latest_annual_filings", lambda cik, limit=4: [_filing("2023-01-01")]
    )

    def boom(filing):
        raise FileNotFoundError("cached html gone")

    monkeypatch.setattr(cd, "extract_sections_from_filing", boom)
    result = build_score_trajectory("1")
    assert result["filings_compared"] == 0
    assert result["points"] == []
    assert result["trends"] == {}

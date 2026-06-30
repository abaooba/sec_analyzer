"""Tests for Ken French factor fetch/parse/cache (offline — no network).

The parser is exercised against small CSV strings shaped exactly like the real
Ken French daily files (preamble lines, a header row, percent values, a trailing
copyright line); the cache and join logic monkeypatch the downloader.
"""

import io
import zipfile

import pandas as pd
import pytest

from backend.app.factors import factor_data as fd

FF5_CSV = """This file was created by using the 202604 CRSP database.
The Tbill return is the simple daily rate ...

,Mkt-RF,SMB,HML,RMW,CMA,RF
20240102,  -0.70,  -0.26,   0.80,   0.68,   0.63,   0.02
20240103,  -1.01,  -1.93,  -0.10,   0.36,  -0.19,   0.02
20240104,  -0.33,   0.23,   0.11,  -0.42,   0.22,   0.02
20240105, -99.99,   0.00,   0.00,   0.00,   0.00,   0.02

Copyright 2026 Eugene F. Fama and Kenneth R. French
"""

MOM_CSV = """This file was created by using the 202604 CRSP database.  It
contains a momentum factor ...

Missing data are indicated by -99.99 or -999.

,Mom
20240102,  -2.11
20240103,   0.58
20240105,  -0.30

Copyright 2026 Eugene F. Fama and Kenneth R. French
"""


def _zip_bytes(inner_name: str, text: str) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(inner_name, text)
    return buffer.getvalue()


def test_parse_ff5_columns_dates_and_decimals():
    frame = fd.parse_french_csv(FF5_CSV)
    assert list(frame.columns) == ["Mkt-RF", "SMB", "HML", "RMW", "CMA", "RF"]
    assert isinstance(frame.index, pd.DatetimeIndex)
    # Percent -> decimal: -0.70% becomes -0.0070.
    assert frame.loc["2024-01-02", "Mkt-RF"] == pytest.approx(-0.0070)
    assert frame.loc["2024-01-03", "SMB"] == pytest.approx(-0.0193)


def test_parse_maps_missing_sentinel_to_nan():
    frame = fd.parse_french_csv(FF5_CSV)
    # The -99.99 sentinel cell becomes NaN; its row-neighbors stay real numbers.
    assert pd.isna(frame.loc["2024-01-05", "Mkt-RF"])
    assert frame.loc["2024-01-05", "RF"] == pytest.approx(0.0002)


def test_parse_stops_at_copyright_footer():
    frame = fd.parse_french_csv(FF5_CSV)
    assert len(frame) == 4  # 4 data rows, copyright line ignored


def test_parse_momentum_single_named_column():
    frame = fd.parse_french_csv(MOM_CSV)
    assert list(frame.columns) == ["Mom"]
    assert frame.loc["2024-01-02", "Mom"] == pytest.approx(-0.0211)


def test_extract_csv_text_reads_inner_csv():
    text = fd._extract_csv_text(_zip_bytes("F-F_x_daily.csv", FF5_CSV))
    assert ",Mkt-RF,SMB,HML,RMW,CMA,RF" in text


def test_read_cached_or_download_caches_after_first_fetch(tmp_path, monkeypatch):
    monkeypatch.setattr(fd.settings, "factor_cache_dir", str(tmp_path))
    monkeypatch.setattr(fd.settings, "factor_cache_ttl_hours", 24.0)
    calls = {"n": 0}

    def fake_download(filename):
        calls["n"] += 1
        return _zip_bytes("inner.csv", FF5_CSV)

    monkeypatch.setattr(fd, "_download_zip_bytes", fake_download)

    first = fd._read_cached_or_download(fd.FF5_DAILY_ZIP)
    second = fd._read_cached_or_download(fd.FF5_DAILY_ZIP)

    assert first == second
    assert calls["n"] == 1  # second call served from the on-disk cache
    assert (tmp_path / fd.FF5_DAILY_ZIP).is_file()


def test_read_cached_or_download_refetches_when_stale(tmp_path, monkeypatch):
    monkeypatch.setattr(fd.settings, "factor_cache_dir", str(tmp_path))
    monkeypatch.setattr(fd.settings, "factor_cache_ttl_hours", 0.0)  # nothing is fresh
    calls = {"n": 0}
    monkeypatch.setattr(
        fd, "_download_zip_bytes",
        lambda filename: (calls.__setitem__("n", calls["n"] + 1), _zip_bytes("i.csv", FF5_CSV))[1],
    )

    fd._read_cached_or_download(fd.FF5_DAILY_ZIP)
    fd._read_cached_or_download(fd.FF5_DAILY_ZIP)
    assert calls["n"] == 2  # TTL=0 forces a re-download every time


def test_load_factor_returns_joins_ff5_and_momentum(tmp_path, monkeypatch):
    monkeypatch.setattr(fd.settings, "factor_cache_dir", str(tmp_path))

    def fake_cached(filename):
        if filename == fd.FF5_DAILY_ZIP:
            return _zip_bytes("ff5.csv", FF5_CSV)
        return _zip_bytes("mom.csv", MOM_CSV)

    monkeypatch.setattr(fd, "_read_cached_or_download", fake_cached)

    combined = fd.load_factor_returns()
    assert list(combined.columns) == ["Mkt-RF", "SMB", "HML", "RMW", "CMA", "RF", "Mom"]
    # Inner join: only dates present in BOTH files survive (2024-01-02, -03, -05).
    assert len(combined) == 3
    assert "2024-01-04" not in combined.index.strftime("%Y-%m-%d")


def test_load_factor_returns_clips_to_window(tmp_path, monkeypatch):
    monkeypatch.setattr(fd.settings, "factor_cache_dir", str(tmp_path))
    monkeypatch.setattr(
        fd, "_read_cached_or_download",
        lambda f: _zip_bytes("c.csv", FF5_CSV if f == fd.FF5_DAILY_ZIP else MOM_CSV),
    )
    combined = fd.load_factor_returns(start="2024-01-03", end="2024-01-03")
    assert list(combined.index.strftime("%Y-%m-%d")) == ["2024-01-03"]

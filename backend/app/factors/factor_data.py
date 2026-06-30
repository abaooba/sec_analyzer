"""Fama-French factor data — fetch + parse the Ken French Data Library CSVs.

This module supplies the *right-hand side* of the factor regression: the daily
returns of the Fama-French 5 research factors (market, size, value,
profitability, investment), the risk-free rate, and the Momentum factor — all
sourced free from the Ken French Data Library.

Why fetch the raw zips ourselves instead of using `pandas_datareader`: the rest
of the app routes every outbound request through `make_http_client`, so a single
TLS / HTTP posture (`TLS_VERIFY`) governs all network I/O. We keep that property
here by downloading the published CSV zips directly and parsing them, rather than
handing network control to a third-party reader with its own HTTP stack.

The published files have a few lines of human-readable preamble, one header row,
then `YYYYMMDD,value,value,...` rows quoted in *percent*, and a trailing
copyright line. `parse_french_csv` tolerates all of that and returns a tidy
DataFrame of *decimal* daily returns indexed by date. Downloaded zips are cached
on disk (they refresh at most daily) so repeated requests don't re-fetch MBs.
"""

import io
import logging
import re
import time
import zipfile
from pathlib import Path

import pandas as pd

from ..config import settings
from ..http_client import make_http_client

logger = logging.getLogger(__name__)

# Published file names in the Ken French Data Library (daily frequency).
FF5_DAILY_ZIP = "F-F_Research_Data_5_Factors_2x3_daily_CSV.zip"
MOMENTUM_DAILY_ZIP = "F-F_Momentum_Factor_daily_CSV.zip"

# The momentum file's single data column; we canonicalize its header to this.
MOMENTUM_COLUMN = "Mom"

# Ken French marks missing observations with these percent sentinels.
MISSING_SENTINELS = (-99.99, -999.0)

# A descriptive User-Agent — some hosts reject requests that send none.
_HTTP_USER_AGENT = "sec_analyzer/factor-attribution (+https://github.com/abaooba/sec_analyzer)"

# A daily data row looks like "19630701,   -0.67,    0.00, ...".
_DATA_ROW = re.compile(r"^\s*(\d{8})\s*,(.*)$")


def _download_zip_bytes(filename: str) -> bytes:
    """Download one Ken French CSV zip and return its raw bytes.

    Goes through make_http_client so TLS_VERIFY (and any future HTTP posture)
    applies here just like the SEC/news fetches. Network-touching — tests
    monkeypatch this.
    """
    url = settings.factor_data_base_url.rstrip("/") + "/" + filename
    headers = {"User-Agent": _HTTP_USER_AGENT}
    with make_http_client(
        headers=headers, timeout=settings.request_timeout, follow_redirects=True
    ) as client:
        response = client.get(url)
        response.raise_for_status()
        return response.content


def _cache_path(filename: str) -> Path:
    return Path(settings.factor_cache_dir) / filename


def _read_cached_or_download(filename: str) -> bytes:
    """Return the zip bytes from the on-disk cache if fresh, else download + cache.

    Freshness is governed by settings.factor_cache_ttl_hours. A failure to write
    the cache (read-only FS, etc.) is logged and ignored — the download still
    succeeds, we just don't get the speed-up next time.
    """
    path = _cache_path(filename)
    ttl_seconds = settings.factor_cache_ttl_hours * 3600

    if path.is_file() and (time.time() - path.stat().st_mtime) < ttl_seconds:
        return path.read_bytes()

    data = _download_zip_bytes(filename)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    except OSError:
        logger.warning("Could not write factor cache to %s", path)
    return data


def _extract_csv_text(zip_bytes: bytes) -> str:
    """Pull the single CSV out of a Ken French zip and decode it.

    The files use latin-1 (a stray non-ASCII byte appears in some preambles), so
    we decode permissively rather than assume UTF-8.
    """
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as archive:
        csv_names = [name for name in archive.namelist() if name.lower().endswith(".csv")]
        if not csv_names:
            raise ValueError("No CSV file found inside the Ken French zip")
        return archive.read(csv_names[0]).decode("latin-1")


def parse_french_csv(text: str) -> pd.DataFrame:
    """Parse a Ken French *daily* CSV into a decimal-returns DataFrame.

    Locates the data block (lines beginning `YYYYMMDD,`), reads the header row
    that precedes it for column names, converts the percent values to decimals,
    and maps the missing-data sentinels to NaN. Returns a DataFrame indexed by a
    `DatetimeIndex` named "date". Pure (no I/O) so it's trivially unit-tested.
    """
    lines = text.splitlines()

    # First data row: the first line that starts with an 8-digit date + comma.
    first_data_idx = next((i for i, line in enumerate(lines) if _DATA_ROW.match(line)), None)
    if first_data_idx is None:
        raise ValueError("No daily data rows found in Ken French CSV")

    # Header row: the nearest non-blank line above the first data row.
    header_idx = first_data_idx - 1
    while header_idx >= 0 and not lines[header_idx].strip():
        header_idx -= 1
    if header_idx < 0:
        raise ValueError("No header row found in Ken French CSV")

    # The header's leading token is the (empty) date column; the rest are factors.
    columns = [token.strip() for token in lines[header_idx].split(",")][1:]
    if not columns:
        raise ValueError("Ken French header row has no factor columns")

    dates: list[str] = []
    rows: list[list[float]] = []
    for line in lines[first_data_idx:]:
        match = _DATA_ROW.match(line)
        if not match:
            # The daily block is contiguous; the first non-data, non-blank line
            # (the copyright footer) ends it.
            if line.strip():
                break
            continue
        values = [value.strip() for value in match.group(2).split(",")]
        if len(values) != len(columns):
            continue  # skip a malformed row rather than misalign columns
        dates.append(match.group(1))
        rows.append([float(value) for value in values])

    frame = pd.DataFrame(rows, columns=columns, index=pd.to_datetime(dates, format="%Y%m%d"))
    frame.index.name = "date"
    frame = frame.mask(frame.isin(MISSING_SENTINELS))  # sentinels -> NaN
    return frame / 100.0  # percent -> decimal


def load_ff5_daily() -> pd.DataFrame:
    """Daily FF5 factors + RF (columns: Mkt-RF, SMB, HML, RMW, CMA, RF)."""
    return parse_french_csv(_extract_csv_text(_read_cached_or_download(FF5_DAILY_ZIP)))


def load_momentum_daily() -> pd.DataFrame:
    """Daily Momentum factor as a one-column DataFrame (column: Mom)."""
    frame = parse_french_csv(_extract_csv_text(_read_cached_or_download(MOMENTUM_DAILY_ZIP)))
    # The file ships a single data column; pin its name regardless of spacing.
    frame = frame.rename(columns={frame.columns[0]: MOMENTUM_COLUMN})
    return frame[[MOMENTUM_COLUMN]]


def load_factor_returns(
    start: str | None = None, end: str | None = None
) -> pd.DataFrame:
    """Combined daily factor table: FF5 + RF + Momentum, aligned on date.

    Inner-joins the two source files (they begin on different dates) and clips to
    the optional [start, end] window. Columns: Mkt-RF, SMB, HML, RMW, CMA, RF, Mom.
    """
    factors = load_ff5_daily().join(load_momentum_daily(), how="inner")
    if start is not None:
        factors = factors[factors.index >= pd.Timestamp(start)]
    if end is not None:
        factors = factors[factors.index <= pd.Timestamp(end)]
    return factors

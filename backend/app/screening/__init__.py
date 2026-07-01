"""Cross-sectional fundamental screen.

Given a universe of tickers, this package computes a handful of classic
quantitative-value / earnings-quality metrics per company (Piotroski F-Score,
Altman Z-Score, Sloan accruals, ROIC, free-cash-flow yield), ranks them against
each other, flags distress and earnings-quality risks, and renders a
color-coded screen table plus a value-vs-quality scatter.

Layering (mirrors `factors/`):
  metrics.py  — pure per-company math over annual snapshots (no I/O)
  ranking.py  — cross-sectional percentile ranks, composites, flags (no I/O)
  render.py   — ANSI table + ASCII/PNG scatter presentation (no I/O except PNG)
  market_data.py — optional market caps via yfinance (the only network piece)
  service.py  — orchestrates ingest -> compute -> rank -> assemble
"""

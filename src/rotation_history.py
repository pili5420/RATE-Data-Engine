"""Same-date cross-sectional technical feature histories for RATE Rotation inputs.

The technical feature calculations are delegated to the existing RATE engine.
This module only replays those calculations at historical as-of dates so the
Rotation 5-session deltas never use today's cross-section or future records.
"""
from __future__ import annotations

from .technical_features import compute_scores, technical_record

SPEC_VERSION = "RATE-DFCS-V1.0"


def build_rotation_feature_histories(stock_histories, benchmark_by_symbol, *, as_of_date, sessions=6):
    symbols = sorted(str(symbol) for symbol in stock_histories)
    if len(symbols) < 20:
        raise ValueError("DATA_INCOMPLETE:ROTATION_UNIVERSE_TOO_SMALL")

    stocks = {}
    benchmarks = {}
    aligned_dates = {}
    for symbol in symbols:
        stock = sorted((dict(row) for row in stock_histories[symbol] if row["trade_date"] <= as_of_date), key=lambda r: r["trade_date"])
        benchmark = sorted((dict(row) for row in benchmark_by_symbol[symbol] if row["trade_date"] <= as_of_date), key=lambda r: r["trade_date"])
        stock_dates = {row["trade_date"] for row in stock}
        benchmark_dates = {row["trade_date"] for row in benchmark}
        aligned = stock_dates & benchmark_dates
        if len(aligned) < 120:
            raise ValueError(f"DATA_INCOMPLETE:ROTATION_HISTORY:{symbol}")
        stocks[symbol] = stock
        benchmarks[symbol] = benchmark
        aligned_dates[symbol] = aligned

    common_dates = set.intersection(*(aligned_dates[s] for s in symbols))
    as_of_sessions = sorted(common_dates)
    if len(as_of_sessions) < sessions or as_of_sessions[-1] != as_of_date:
        raise ValueError(f"DATA_INCOMPLETE:ROTATION_ASOF_SESSIONS:{as_of_date}")
    selected_dates = as_of_sessions[-sessions:]
    histories = {symbol: {"rs_history": [], "mo_history": [], "volume_ratio_5_20_history": []} for symbol in symbols}

    for session_date in selected_dates:
        stock_prefix = {
            symbol: [{**row, "symbol": symbol} for row in stocks[symbol] if row["trade_date"] <= session_date]
            for symbol in symbols
        }
        benchmark_prefix = {
            symbol: [row for row in benchmarks[symbol] if row["trade_date"] <= session_date]
            for symbol in symbols
        }
        # compute_scores calculates RS/MO percentiles over this same as-of
        # universe only. No record after session_date is passed to it.
        scored = compute_scores(
            [stock_prefix[symbol] for symbol in symbols],
            benchmark_by_symbol=benchmark_prefix,
        )
        if len(scored) != len(symbols):
            raise ValueError("DATA_INCOMPLETE:ROTATION_CROSS_SECTION")
        for score in scored:
            symbol = str(score["symbol"])
            stock = stock_prefix[symbol]
            benchmark = benchmark_prefix[symbol]
            technical = technical_record(stock, benchmark)
            denominator = float(technical["AVG_VOLUME_20"])
            if denominator <= 0:
                raise ValueError(f"DATA_INCOMPLETE:VOL_RATIO_5_20:{symbol}:{session_date}")
            ratio = float(technical["AVG_VOLUME_5"]) / denominator
            source_dates = [row["trade_date"] for row in stock if row["trade_date"] in set(r["trade_date"] for r in benchmark)]
            source_timestamps = [row.get("source_timestamp") for row in stock if row["trade_date"] in set(source_dates)]
            lineage = {
                "trade_date": session_date,
                "source_dates": source_dates,
                "source_timestamps": source_timestamps,
                "benchmark_dates": [row["trade_date"] for row in benchmark if row["trade_date"] in set(source_dates)],
                "benchmark_source_timestamps": [row.get("source_timestamp") for row in benchmark if row["trade_date"] in set(source_dates)],
                "calculation_spec_version": SPEC_VERSION,
            }
            histories[symbol]["rs_history"].append({**lineage, "value": float(score["technical_features"]["RS"])})
            histories[symbol]["mo_history"].append({**lineage, "value": float(score["technical_features"]["MO"])})
            histories[symbol]["volume_ratio_5_20_history"].append({
                "trade_date": session_date,
                "source_dates": [row["trade_date"] for row in stock[-20:]],
                "source_timestamps": [row.get("source_timestamp") for row in stock[-20:]],
                "value": ratio,
                "calculation_spec_version": SPEC_VERSION,
            })

    for symbol in symbols:
        for field in ("rs_history", "mo_history", "volume_ratio_5_20_history"):
            if len(histories[symbol][field]) < sessions:
                raise ValueError(f"DATA_INCOMPLETE:ROTATION_HISTORY:{symbol}")
    return histories

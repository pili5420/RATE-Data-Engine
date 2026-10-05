"""Materialize bounded official stock/benchmark history for RATE production source runs.

This preflight is intentionally narrow:
- exact Control Center-approved production acquisition universe only
- official TWSE/TPEx historical endpoints only
- completed sessions strictly before the requested trading date
- finite month and runtime budgets
- no fixture, stale, local-cache, synthetic, or alternate-provider fallback

If the requested minimum history cannot be produced within the configured
limits, the command fails closed before the production source bundle build.
"""
from __future__ import annotations

import argparse
import json
import time
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from scripts.bootstrap_tpex_history import TPEx_SYMBOLS, extract_symbol_month_rows
from scripts.build_production_source_bundle_from_official import _month_cursor, _rows
from src.benchmark_history import normalize_twse_date
from src.historical_store import MAX_SESSIONS, PersistentHistoricalStore, normalize_benchmark_record, normalize_stock_record
from src.sources.tpex import TPExAdapter, normalize_tpex_date
from src.sources.twse import TWSEAdapter
from src.sources.tpex_date_binding import build_material, material_path
from src.cer074_acceptance import atomic_write_json

DEFAULT_MAX_MONTHS = 12
DEFAULT_MIN_SESSIONS = 180
DEFAULT_MAX_RUNTIME_SECONDS = 900


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _finite_periods(trading_date: str, max_months: int) -> list[str]:
    if max_months < 1:
        raise RuntimeError("HISTORY_MAX_MONTHS_INVALID")
    cursor = _month_cursor(date.fromisoformat(trading_date))
    return [next(cursor) for _ in range(max_months)]


def _load_contract(path: Path) -> list[str]:
    obj = json.loads(path.read_text(encoding="utf-8"))
    if obj.get("artifact") != "RATE_PRODUCTION_UNIVERSE_CONTRACT" or obj.get("validation_status") != "PASS":
        raise RuntimeError("PRODUCTION_UNIVERSE_CONTRACT_INVALID")
    symbols = [str(x) for x in obj.get("approved_universe") or []]
    if len(symbols) != 30 or len(set(symbols)) != 30 or obj.get("required_count") != 30:
        raise RuntimeError("PRODUCTION_UNIVERSE_CONTRACT_COUNT_INVALID")
    tpex = set(TPEx_SYMBOLS)
    if not tpex.issubset(set(symbols)):
        raise RuntimeError("PRODUCTION_UNIVERSE_TPEX_BINDING_INVALID")
    return symbols


def _core_stock(record: Mapping[str, Any]) -> tuple[Any, ...]:
    return tuple(record.get(key) for key in ("symbol", "market", "trade_date", "open", "high", "low", "close", "volume", "turnover"))


def _merge_stock_records(existing: list[dict[str, Any]], incoming: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for row in [*existing, *incoming]:
        trade_date = str(row.get("trade_date") or "")
        if not trade_date:
            raise RuntimeError("HISTORY_TRADE_DATE_MISSING")
        if trade_date in merged and _core_stock(merged[trade_date]) != _core_stock(row):
            raise RuntimeError(f"HISTORY_RECORD_CONFLICT:{row.get('symbol')}:{trade_date}")
        merged.setdefault(trade_date, dict(row))
    return [merged[key] for key in sorted(merged)]


def _twse_month_rows(adapter: TWSEAdapter, symbol: str, period: str, trading_date: str) -> list[dict[str, Any]]:
    result = adapter.fetch_historical_symbol(symbol, period)
    records = []
    for row in _rows(result.get("raw_payload")):
        raw_date = row.get("trade_date") or row.get("Date") or row.get("日期")
        if raw_date is None:
            continue
        normalized_date = normalize_twse_date(raw_date)
        if normalized_date >= trading_date:
            continue
        try:
            record = normalize_stock_record(
                {
                    "symbol": symbol,
                    "market": "TWSE",
                    "trade_date": normalized_date,
                    "open": row.get("open", row.get("OpeningPrice", row.get("開盤價", row.get("Open")))),
                    "high": row.get("high", row.get("HighestPrice", row.get("最高價", row.get("High")))),
                    "low": row.get("low", row.get("LowestPrice", row.get("最低價", row.get("Low")))),
                    "close": row.get("close", row.get("ClosingPrice", row.get("收盤價", row.get("Close")))),
                    "volume": row.get("volume", row.get("TradeVolume", row.get("成交股數", row.get("TradingShares")))),
                    "turnover": row.get("turnover", row.get("TradeValue", row.get("成交金額", row.get("TransactionAmount")))),
                },
                source="TWSE_STOCK_DAY",
                source_timestamp=result.get("source_timestamp"),
                ingested_at=result.get("retrieval_timestamp"),
            )
        except (TypeError, ValueError):
            continue
        records.append(record)
    return records


def _tpex_month_rows(adapter: TPExAdapter, symbol: str, period: str, trading_date: str) -> list[dict[str, Any]]:
    result = adapter.fetch_historical_symbol(symbol, period)
    return [row for row in extract_symbol_month_rows(result, symbol, period) if str(row.get("trade_date")) < trading_date]


def _number(value: Any) -> float:
    text = str(value).strip().replace(",", "")
    if text in {"", "-", "--", "None", "null"}:
        raise ValueError("BENCHMARK_NUMERIC_VALUE_MISSING")
    return float(text.replace("(", "-").replace(")", ""))


def _benchmark_month_rows(adapter: Any, market: str, period: str, trading_date: str) -> list[dict[str, Any]]:
    result = adapter.fetch_historical_benchmark(period)
    benchmark_symbol = "TAIEX" if market == "TWSE" else "TPEX"
    records = []
    for row in _rows(result.get("raw_payload")):
        raw_date = row.get("trade_date") or row.get("Date") or row.get("日期")
        close = row.get("close", row.get("ClosingIndex", row.get("收盤指數", row.get("收盤價"))))
        if raw_date is None or close is None:
            continue
        normalized_date = normalize_twse_date(raw_date) if market == "TWSE" else normalize_tpex_date(raw_date)
        if normalized_date >= trading_date:
            continue
        try:
            records.append(
                normalize_benchmark_record(
                    {"trade_date": normalized_date, "close": _number(close)},
                    benchmark_symbol=benchmark_symbol,
                    market=market,
                    source=f"{market}_BENCHMARK_HISTORY",
                    source_timestamp=result.get("source_timestamp"),
                    ingested_at=result.get("retrieval_timestamp"),
                )
            )
        except (TypeError, ValueError):
            continue
    return records


def _replace_benchmark(store: PersistentHistoricalStore, benchmark_symbol: str, records: list[dict[str, Any]]) -> dict[str, Any]:
    by_date: dict[str, dict[str, Any]] = {}
    for row in records:
        key = str(row.get("trade_date") or "")
        if not key:
            raise RuntimeError(f"BENCHMARK_TRADE_DATE_MISSING:{benchmark_symbol}")
        if key in by_date and by_date[key] != row:
            raise RuntimeError(f"BENCHMARK_HISTORY_CONFLICT:{benchmark_symbol}:{key}")
        by_date[key] = dict(row)
    retained = [by_date[key] for key in sorted(by_date)][-MAX_SESSIONS:]
    store._write("benchmark", benchmark_symbol, retained)
    return {"record_count": len(retained), "trimmed_count": max(0, len(by_date) - len(retained))}


def _check_deadline(started: float, max_runtime_seconds: int) -> None:
    if time.monotonic() - started >= max_runtime_seconds:
        raise RuntimeError("OFFICIAL_HISTORY_RUNTIME_HARD_LIMIT_REACHED")


def _materialize_stock(
    *,
    store: PersistentHistoricalStore,
    symbol: str,
    market: str,
    trading_date: str,
    periods: list[str],
    minimum_sessions: int,
    started: float,
    max_runtime_seconds: int,
    adapter: Any,
) -> dict[str, Any]:
    existing = [row for row in store.load_stock(symbol) if str(row.get("trade_date")) < trading_date and row.get("market") == market]
    records = list(existing)
    periods_used = 0
    if len(records) < minimum_sessions:
        for period in periods:
            _check_deadline(started, max_runtime_seconds)
            incoming = _twse_month_rows(adapter, symbol, period, trading_date) if market == "TWSE" else _tpex_month_rows(adapter, symbol, period, trading_date)
            records = _merge_stock_records(records, incoming)
            periods_used += 1
            if len(records) >= minimum_sessions:
                break
    if len(records) < minimum_sessions:
        raise RuntimeError(f"OFFICIAL_MARKET_HISTORY_HARD_LIMIT_REACHED:{symbol}:{len(records)}<{minimum_sessions}:max_months={len(periods)}")
    result = store.materialize_stock(symbol, records)
    persisted = [row for row in store.load_stock(symbol) if str(row.get("trade_date")) < trading_date]
    if len(persisted) < minimum_sessions or any(str(row.get("trade_date")) >= trading_date for row in persisted):
        raise RuntimeError(f"OFFICIAL_MARKET_HISTORY_MATERIALIZATION_FAILED:{symbol}")
    return {
        "symbol": symbol,
        "market": market,
        "sessions": len(persisted),
        "periods_used": periods_used,
        "network_fetch_required": periods_used > 0,
        "earliest_trade_date": persisted[0]["trade_date"],
        "latest_trade_date": persisted[-1]["trade_date"],
        "trimmed_count": result.get("trimmed_count", 0),
        "status": "PASS",
    }


def _materialize_benchmark(
    *,
    store: PersistentHistoricalStore,
    market: str,
    trading_date: str,
    periods: list[str],
    minimum_sessions: int,
    started: float,
    max_runtime_seconds: int,
    adapter: Any,
) -> dict[str, Any]:
    benchmark_symbol = "TAIEX" if market == "TWSE" else "TPEX"
    existing = [row for row in store.load_benchmark(benchmark_symbol) if str(row.get("trade_date")) < trading_date]
    by_date = {str(row["trade_date"]): dict(row) for row in existing}
    periods_used = 0
    if len(by_date) < minimum_sessions:
        for period in periods:
            _check_deadline(started, max_runtime_seconds)
            for row in _benchmark_month_rows(adapter, market, period, trading_date):
                key = str(row["trade_date"])
                previous = by_date.get(key)
                if previous is not None and float(previous.get("close")) != float(row.get("close")):
                    raise RuntimeError(f"BENCHMARK_HISTORY_CONFLICT:{benchmark_symbol}:{key}")
                by_date.setdefault(key, row)
            periods_used += 1
            if len(by_date) >= minimum_sessions:
                break
    records = [by_date[key] for key in sorted(by_date)]
    if len(records) < minimum_sessions:
        raise RuntimeError(f"OFFICIAL_BENCHMARK_HISTORY_HARD_LIMIT_REACHED:{benchmark_symbol}:{len(records)}<{minimum_sessions}:max_months={len(periods)}")
    result = _replace_benchmark(store, benchmark_symbol, records)
    persisted = [row for row in store.load_benchmark(benchmark_symbol) if str(row.get("trade_date")) < trading_date]
    if len(persisted) < minimum_sessions or any(str(row.get("trade_date")) >= trading_date for row in persisted):
        raise RuntimeError(f"OFFICIAL_BENCHMARK_HISTORY_MATERIALIZATION_FAILED:{benchmark_symbol}")
    return {
        "benchmark_symbol": benchmark_symbol,
        "market": market,
        "sessions": len(persisted),
        "periods_used": periods_used,
        "network_fetch_required": periods_used > 0,
        "earliest_trade_date": persisted[0]["trade_date"],
        "latest_trade_date": persisted[-1]["trade_date"],
        "trimmed_count": result.get("trimmed_count", 0),
        "status": "PASS",
    }


def materialize(
    *,
    trading_date: str,
    universe_contract: Path,
    history_root: Path,
    evidence_output: Path,
    max_months: int = DEFAULT_MAX_MONTHS,
    minimum_sessions: int = DEFAULT_MIN_SESSIONS,
    max_runtime_seconds: int = DEFAULT_MAX_RUNTIME_SECONDS,
    twse_adapter: TWSEAdapter | None = None,
    tpex_adapter: TPExAdapter | None = None,
) -> dict[str, Any]:
    started = time.monotonic()
    symbols = _load_contract(universe_contract)
    periods = _finite_periods(trading_date, max_months)
    store = PersistentHistoricalStore(history_root)
    twse_adapter = twse_adapter or TWSEAdapter()
    tpex_adapter = tpex_adapter or TPExAdapter()
    rows = []
    benchmark_rows = []
    # Keep exact-date daily input separate from the strictly prior technical history.
    date_bound_path = material_path(history_root, trading_date)
    try:
        date_bound_sources = {}
        for symbol in TPEx_SYMBOLS:
            _check_deadline(started, max_runtime_seconds)
            date_bound_sources[symbol] = tpex_adapter.fetch_historical_symbol(symbol, periods[0])
        _check_deadline(started, max_runtime_seconds)
        date_bound_material = build_material(trading_date, date_bound_sources, TPEx_SYMBOLS)
    except Exception as exc:
        date_bound_material = {"validation_status": "FAIL_CLOSED", "requested_trading_date": trading_date,
                               "blocking_reason": str(exc), "fallback_used": False}
    atomic_write_json(date_bound_path, date_bound_material)
    try:
        for symbol in symbols:
            _check_deadline(started, max_runtime_seconds)
            market = "TPEX" if symbol in set(TPEx_SYMBOLS) else "TWSE"
            adapter = tpex_adapter if market == "TPEX" else twse_adapter
            rows.append(
                _materialize_stock(
                    store=store,
                    symbol=symbol,
                    market=market,
                    trading_date=trading_date,
                    periods=periods,
                    minimum_sessions=minimum_sessions,
                    started=started,
                    max_runtime_seconds=max_runtime_seconds,
                    adapter=adapter,
                )
            )
        for market, adapter in (("TWSE", twse_adapter), ("TPEX", tpex_adapter)):
            _check_deadline(started, max_runtime_seconds)
            benchmark_rows.append(
                _materialize_benchmark(
                    store=store,
                    market=market,
                    trading_date=trading_date,
                    periods=periods,
                    minimum_sessions=minimum_sessions,
                    started=started,
                    max_runtime_seconds=max_runtime_seconds,
                    adapter=adapter,
                )
            )
        status = "PASS"
        reason = None
    except Exception as exc:
        status = "FAIL_CLOSED"
        reason = str(exc)
    payload = {
        "artifact": "RATE_PRODUCTION_HISTORY_STORE_MATERIALIZATION_EVIDENCE",
        "status": status,
        "blocking_reason": reason,
        "trading_date": trading_date,
        "universe_contract": str(universe_contract),
        "history_root": str(history_root),
        "required_symbols": len(symbols),
        "symbols_materialized": len(rows),
        "minimum_sessions": minimum_sessions,
        "max_months_per_symbol_or_benchmark": max_months,
        "max_runtime_seconds": max_runtime_seconds,
        "elapsed_seconds": round(time.monotonic() - started, 3),
        "stock_rows": rows,
        "benchmark_rows": benchmark_rows,
        "date_bound_market_daily": {"path": str(date_bound_path),
            "validation_status": date_bound_material["validation_status"],
            "historical_material_id": date_bound_material.get("historical_material_id"),
            "historical_material_hash": date_bound_material.get("historical_material_hash"),
            "blocking_reason": date_bound_material.get("blocking_reason")},
        "fallback_used": False,
        "alternate_provider_used": False,
        "fixture_used": False,
        "synthetic_used": False,
        "current_trading_date_persisted": False,
        "production_state_modified": "NO",
        "generated_at": _now(),
    }
    evidence_output.parent.mkdir(parents=True, exist_ok=True)
    evidence_output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return payload


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--trading-date", required=True)
    ap.add_argument("--universe-contract", required=True)
    ap.add_argument("--history-root", default="data/staging/step5a_history")
    ap.add_argument("--evidence-output", default="artifacts/production_source_acquisition/RATE_PRODUCTION_HISTORY_STORE_MATERIALIZATION_EVIDENCE.json")
    ap.add_argument("--max-months", type=int, default=DEFAULT_MAX_MONTHS)
    ap.add_argument("--minimum-sessions", type=int, default=DEFAULT_MIN_SESSIONS)
    ap.add_argument("--max-runtime-seconds", type=int, default=DEFAULT_MAX_RUNTIME_SECONDS)
    args = ap.parse_args()
    result = materialize(
        trading_date=args.trading_date,
        universe_contract=Path(args.universe_contract),
        history_root=Path(args.history_root),
        evidence_output=Path(args.evidence_output),
        max_months=args.max_months,
        minimum_sessions=args.minimum_sessions,
        max_runtime_seconds=args.max_runtime_seconds,
    )
    print(json.dumps({"status": result["status"], "symbols_materialized": result["symbols_materialized"], "blocking_reason": result.get("blocking_reason")}))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())

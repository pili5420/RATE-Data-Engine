"""Bounded full-universe acquisition using existing official source owners."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
import json
import os
from pathlib import Path
import time

from .full_market_catalogue import build_catalogue
from .full_market_rotation import bind_full_universe
from .historical_store import PersistentHistoricalStore
from .phase2_production import contract
from .production_live_state import require
from .sources.twse import TWSEAdapter
from .sources.tpex import TPExAdapter


def refresh_fundamentals(symbols, markets, trading_date, history_root, *, started, budget):
    from scripts import build_live_source_bundle as owner
    from scripts.materialize_production_history_store import _finite_periods, _check_deadline
    root = str(Path(history_root) / "fundamental")
    store = owner.FundamentalHistoryStoreV2(root)
    adapter = owner.MOPSHistoricalFundamentalAdapter()
    months = [p[:4] + "-" + p[4:] for p in _finite_periods(trading_date, 7)][1:]
    asof = date.fromisoformat(trading_date)
    year, quarter = asof.year, (asof.month - 1) // 3
    if quarter == 0:
        year, quarter = year - 1, 4
    eps_periods = [divmod(year * 4 + quarter - 1 - offset, 4) for offset in range(10)]
    revenues, eps = [], []
    for market in ("TWSE", "TPEX"):
        for month in months:
            _check_deadline(started, budget)
            revenues.extend(adapter.fetch_revenue_period(market, month))
        for fiscal_year, zero_based_quarter in eps_periods:
            _check_deadline(started, budget)
            eps.extend(adapter.fetch_eps_period(market, fiscal_year, zero_based_quarter + 1))
    store.upsert(revenues, eps)
    previous_root = os.environ.get("RATE_STAGING_FUNDAMENTAL_STORE_ROOT")
    os.environ["RATE_STAGING_FUNDAMENTAL_STORE_ROOT"] = root
    try:
        return owner._fundamental_history(symbols, markets, trading_date)
    except RuntimeError as exc:
        raise RuntimeError("HISTORICAL_WARMUP_REQUIRED:" + str(exc)) from exc
    finally:
        if previous_root is None:
            os.environ.pop("RATE_STAGING_FUNDAMENTAL_STORE_ROOT", None)
        else:
            os.environ["RATE_STAGING_FUNDAMENTAL_STORE_ROOT"] = previous_root


def iso_receipt_time(value):
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        parsed = parsedate_to_datetime(str(value))
    require(parsed.tzinfo is not None, "SOURCE_RECEIPT_TIME_INVALID")
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def materialize_full_market(trading_date, history_root, *, max_months=12, max_runtime_seconds=1800):
    from scripts.materialize_production_history_store import (
        _finite_periods, _materialize_stock, _materialize_benchmark, _benchmark_month_rows,
        _replace_benchmark, _check_deadline)
    from scripts.build_production_source_bundle_from_official import _rows, _raw_market_row
    from scripts.build_live_source_bundle import _institutional_histories, _tdcc_history
    catalogue = build_catalogue(trading_date)
    symbols, markets = bind_full_universe(catalogue, contract(), trading_date, [])
    started = time.monotonic()
    periods = _finite_periods(trading_date, max_months)
    store = PersistentHistoricalStore(history_root)
    adapters = {"TWSE": TWSEAdapter(), "TPEX": TPExAdapter()}
    stocks, benchmark, receipts = {}, {}, {}
    # The independent current-day response is never replaced by the history store.
    for market, adapter in adapters.items():
        response = adapter.fetch_daily()
        raw_rows = _rows(response.get("raw_payload"))
        wanted = {symbol for symbol in symbols if markets[symbol] == market}
        current = {}
        for row in raw_rows:
            symbol = str(row.get("Code") or row.get("SecuritiesCompanyCode") or row.get("symbol") or "").strip()
            if symbol not in wanted:
                continue
            require(symbol not in current, "CURRENT_DAILY_DUPLICATE:" + symbol)
            require(row.get("Date") or row.get("trade_date") or row.get("trading_date"), "CURRENT_DAILY_DATE_MISSING:" + symbol)
            require(any(row.get(key) is not None for key in ("turnover", "TradeValue", "TradingValue", "TransactionAmount")),
                    "CURRENT_DAILY_TURNOVER_MISSING:" + symbol)
            normalized = _raw_market_row(row, source=market, trading_date=trading_date)
            current[symbol] = {**normalized, "market": market, "source_timestamp": response["source_timestamp"],
                               "retrieval_timestamp": response["retrieval_timestamp"],
                               "endpoint": response["endpoint"], "content_hash": response["content_hash"]}
        require(set(current) == wanted, "FULL_MARKET_CURRENT_DAILY_INCOMPLETE:" + ",".join(sorted(wanted - set(current))))
        receipts[market] = {key: value for key, value in response.items() if key != "raw_payload"}
        for symbol in sorted(wanted):
            _check_deadline(started, max_runtime_seconds)
            try:
                _materialize_stock(store=store, symbol=symbol, market=market, trading_date=trading_date,
                    periods=periods, minimum_sessions=179, started=started,
                    max_runtime_seconds=max_runtime_seconds, adapter=adapter)
            except RuntimeError as exc:
                raise RuntimeError("HISTORICAL_WARMUP_REQUIRED:" + str(exc)) from exc
            prior = [row for row in store.load_stock(symbol) if row["trade_date"] < trading_date]
            stocks[symbol] = [*prior[-219:], current[symbol]]
        # Existing normalization owns the current benchmark as well as its history.
        next_day = (date.fromisoformat(trading_date) + timedelta(days=1)).isoformat()
        key = "TAIEX" if market == "TWSE" else "TPEX"
        current_benchmark = [row for row in _benchmark_month_rows(adapter, market, periods[0], next_day)
                             if row["trade_date"] == trading_date]
        require(len(current_benchmark) == 1, "CURRENT_BENCHMARK_MISSING:" + market)
        retained = [row for row in store.load_benchmark(key) if row["trade_date"] < trading_date]
        _replace_benchmark(store, key, retained + current_benchmark)
        try:
            _materialize_benchmark(store=store, market=market, trading_date=next_day,
                periods=periods, minimum_sessions=180, started=started,
                max_runtime_seconds=max_runtime_seconds, adapter=adapter)
        except RuntimeError as exc:
            raise RuntimeError("HISTORICAL_WARMUP_REQUIRED:" + str(exc)) from exc
        benchmark[market] = [row for row in store.load_benchmark(key) if row["trade_date"] <= trading_date]
        require(benchmark[market][-1]["trade_date"] == trading_date, "CURRENT_BENCHMARK_MISSING:" + market)
    institutional, institutional_evidence = _institutional_histories(
        adapters["TWSE"], adapters["TPEX"], symbols, markets, stocks, trading_date)
    institutional = {symbol: [{**row, "trade_date": row["trading_date"], "source": markets[symbol]}
                              for row in rows] for symbol, rows in institutional.items()}
    tdcc = _tdcc_history(symbols, stocks, trading_date)
    require(not os.getenv("RATE_CER073_ACCEPTED_FUNDAMENTAL_CROSS_SECTION"), "PHASE2_SEED_FUNDAMENTAL_OVERRIDE_FORBIDDEN")
    fundamental = refresh_fundamentals(symbols, markets, trading_date, history_root,
                                      started=started, budget=max_runtime_seconds)
    evidence = json.loads(Path("artifacts/RATE_CER073_FUNDAMENTAL_HISTORY_EVIDENCE.json").read_bytes())
    require(evidence.get("validation_status") == "PASS" and evidence.get("fixture_used") is False,
            "FULL_MARKET_FUNDAMENTAL_INCOMPLETE")
    lineage = {row["symbol"]: row["source_lineage"] for row in evidence["symbols"]}
    fundamental_rows = []
    for symbol in symbols:
        require(symbol in lineage, "FULL_MARKET_FUNDAMENTAL_INCOMPLETE:" + symbol)
        disclosures = [row["official_disclosure_date"] for group in lineage[symbol].values() for row in group]
        fundamental_rows.append({"symbol": symbol, **fundamental[symbol], "source": "MOPS",
            "as_of_date": trading_date, "source_timestamp": max(disclosures), "source_lineage": lineage[symbol]})
    source_receipts = []
    def receipt(domain, source, value, role="SOURCE_RETRIEVAL_TIMESTAMP"):
        source_receipts.append({"domain": domain, "source": source, "normalization_status": "PASS",
                                "retrieval_timestamp": iso_receipt_time(value), "timestamp_role": role})
    for market in ("TWSE", "TPEX"):
        receipt("market_daily", market, receipts[market]["retrieval_timestamp"])
        receipt("benchmark", market, benchmark[market][-1]["ingested_at"])
        for symbol in symbols:
            if markets[symbol] == market:
                receipt("institutional", market, institutional[symbol][-1]["source_timestamp"])
    for rows in tdcc.values():
        receipt("large_holder", "TDCC", max(row["retrieval_timestamp"] for row in rows))
    receipt("fundamental", "MOPS", datetime.now(timezone.utc).isoformat(), "DISCLOSURE_STORE_READ_COMPLETED_AT")
    for market in catalogue["markets"]:
        receipt("trading_metadata", market["market"], market["source_receipt"]["classification"]["retrieved_at"])
    return catalogue, {"stock_histories": stocks,
        "benchmark_by_symbol": {symbol: benchmark[markets[symbol]] for symbol in symbols},
        "institutional_histories": institutional, "tdcc_histories": tdcc,
        "fundamental_records": fundamental_rows, "current_daily_receipts": receipts,
        "institutional_evidence": institutional_evidence, "fundamental_evidence": evidence,
        "normalized_source_receipts": source_receipts}

"""Bounded orchestration of existing official owners; no derived ranking state."""
from __future__ import annotations

import copy
from datetime import date, datetime, timezone
from http.client import IncompleteRead
import json
from pathlib import Path
import tempfile
import time
from urllib.error import HTTPError, URLError

from .full_market_history import contract, load_checkpoint, persist_symbol, validate_plan, validate_authority
from .production_live_state import require


def retry(call, *, started, budget, sleep=time.sleep, clock=time.monotonic):
    for attempt in range(contract()["max_attempts"]):
        require(clock() - started < budget, "WARMUP_RUNTIME_BUDGET_EXHAUSTED")
        try:
            value = call()
            require(clock() - started < budget, "WARMUP_RUNTIME_BUDGET_EXHAUSTED")
            return value
        except (IncompleteRead, ConnectionError, TimeoutError, URLError, json.JSONDecodeError) as exc:
            if isinstance(exc, HTTPError) and exc.code not in (408, 429, 500, 502, 503, 504):
                raise
            if attempt + 1 == contract()["max_attempts"]:
                raise RuntimeError("OFFICIAL_HISTORY_TRANSPORT_FAILED") from exc
            delay = 2 ** attempt
            require(clock() - started + delay < budget, "WARMUP_RUNTIME_BUDGET_EXHAUSTED")
            sleep(delay)


class ReceiptAdapter:
    def __init__(self, owner, started, budget, responses=None):
        self.owner, self.started, self.budget = owner, started, budget
        self.responses = responses if responses is not None else {}
        self.receipts = {"stock": [], "benchmark": [], "institutional": []}

    def __getattr__(self, name):
        method = getattr(self.owner, name)
        domain = {"fetch_historical_symbol": "stock", "fetch_historical_benchmark": "benchmark",
                  "fetch_t86": "institutional", "fetch_institutional_daily": "institutional"}.get(name)
        if domain is None:
            return method
        def invoke(*args, **kwargs):
            require(time.monotonic() - self.started < self.budget, "WARMUP_RUNTIME_BUDGET_EXHAUSTED")
            key = json.dumps([type(self.owner).__name__, name, args, kwargs], sort_keys=True)
            # Scope is one shard/process. Failed calls never populate the memo;
            # receipt timestamps and body hashes remain those of the actual fetch.
            if key not in self.responses:
                self.responses[key] = retry(lambda: method(*args, **kwargs), started=self.started, budget=self.budget)
            result = copy.deepcopy(self.responses[key])
            self.receipts[domain].append({"endpoint": result["endpoint"], "content_hash": result["content_hash"],
                "retrieved_at": result["retrieval_timestamp"], "parse_status": "PASS", "request": {"method": name, "arguments": list(args)}})
            return result
        return invoke


def acquire_fundamentals(symbols, market, plan, workspace, started, *, evidence_root=None, authority=None):
    from scripts.materialize_production_history_store import _finite_periods
    from .sources.fundamental_history import EPSPeriodNotAvailable, FundamentalHistoryStoreV2, MOPSHistoricalFundamentalAdapter
    store = FundamentalHistoryStoreV2(Path(workspace) / "fundamental")
    adapter = MOPSHistoricalFundamentalAdapter(warmup_evidence_root=evidence_root if evidence_root is not None else workspace,
        evidence_context={"plan_id": plan["plan_id"], "acquisition_runtime_authority": authority or plan["runtime_authority"]})
    months = [p[:4] + "-" + p[4:] for p in _finite_periods(plan["as_of"], 7)][1:]
    asof = date.fromisoformat(plan["completed_through"])
    ordinal = asof.year * 4 + (asof.month - 1) // 3 - 1
    target_eps_periods = contract()["eps_quarters"] + 2
    # Preserve the existing ten available-quarter acquisition window, but allow
    # exactly one leading quarter to be officially not-yet-published. A no-data
    # response after history has started is a real gap and remains fail-closed.
    periods = [(n // 4, n % 4 + 1) for n in range(ordinal, ordinal - target_eps_periods - 1, -1)]
    revenues, eps = [], []
    budget = contract()["max_shard_seconds"]
    for month in months:
        revenues.extend(retry(lambda: adapter.fetch_revenue_period(market, month), started=started, budget=budget))
    available_eps_periods = 0
    leading_unavailable = 0
    for year, quarter in periods:
        try:
            rows = retry(lambda: adapter.fetch_eps_period(market, year, quarter), started=started, budget=budget)
        except EPSPeriodNotAvailable as exc:
            if available_eps_periods or leading_unavailable:
                raise RuntimeError("FUNDAMENTAL_EPS_HISTORY_GAP") from exc
            leading_unavailable += 1
            continue
        eps.extend(rows)
        available_eps_periods += 1
        if available_eps_periods == target_eps_periods:
            break
    require(available_eps_periods == target_eps_periods, "FUNDAMENTAL_EPS_HISTORY_INSUFFICIENT")
    selected = store.select_asof(store.upsert(revenues, eps), symbols, plan["completed_through"])
    result = {}
    for symbol in symbols:
        rev = sorted(selected[symbol]["revenue"].values(), key=lambda r: r["revenue_period"])[-3:]
        quarters = sorted(selected[symbol]["eps"].values(), key=lambda r: (r["fiscal_year"], r["quarter"]))[-8:]
        result[symbol] = {"revenue": rev, "eps": quarters,
                          "failures": [r for r in getattr(adapter, "row_failures", []) if r["symbol"] == symbol]}
    return result


def acquire_symbol(symbol, market, plan, adapter, workspace, fundamental, started):
    from scripts.materialize_production_history_store import _finite_periods, _materialize_stock, _materialize_benchmark
    from scripts.build_live_source_bundle import _institutional_histories, _tdcc_history
    from .historical_store import PersistentHistoricalStore
    from .sources.tdcc_historical import TDCC_HISTORICAL_PAGE
    from .sources.twse import TWSEAdapter
    from .sources.tpex import TPExAdapter
    store = PersistentHistoricalStore(Path(workspace) / ("stock-" + symbol))
    cfg = contract()
    periods = _finite_periods(plan["as_of"], cfg["max_months"])
    kwargs = {"store": store, "market": market, "trading_date": plan["as_of"], "periods": periods,
              "minimum_sessions": 180, "started": started, "max_runtime_seconds": cfg["max_shard_seconds"], "adapter": adapter}
    _materialize_stock(symbol=symbol, **kwargs)
    _materialize_benchmark(**kwargs)
    stocks = store.load_stock(symbol)
    benchmark = store.load_benchmark("TAIEX" if market == "TWSE" else "TPEX")
    institutional, _ = _institutional_histories(adapter if market == "TWSE" else TWSEAdapter(),
        adapter if market == "TPEX" else TPExAdapter(), [symbol], {symbol: market}, {symbol: stocks}, plan["completed_through"])
    tdcc = retry(lambda: _tdcc_history([symbol], {symbol: stocks}, plan["completed_through"]),
                 started=started, budget=cfg["max_shard_seconds"])[symbol]
    tdcc_receipts = [{"endpoint": TDCC_HISTORICAL_PAGE, "content_hash": row["raw_lineage"][0]["response_sha256"],
                      "retrieved_at": row["retrieval_timestamp"], "parse_status": "PASS"} for row in tdcc]
    fundamental_receipts = [{"endpoint": row["endpoint"], "content_hash": row["content_hash"],
        "retrieved_at": row["retrieval_timestamp"], "parse_status": "PASS"} for row in fundamental["revenue"] + fundamental["eps"]]
    return {"artifact": "RATE_FULL_MARKET_SYMBOL_HISTORY", "plan_id": plan["plan_id"], "as_of": plan["as_of"],
            "symbol": symbol, "market": market, "stock": stocks, "benchmark": benchmark,
            "institutional": institutional[symbol], "tdcc": tdcc, "fundamental": fundamental,
            "source_receipts": {**adapter.receipts, "tdcc": tdcc_receipts, "fundamental": fundamental_receipts},
            "fallback_used": False}


def acquire_shard(plan, shard_id, durable_root, output_root, *, authority):
    validate_authority(authority)
    validate_plan(plan)
    matches = [s for s in plan["shards"] if s["shard_id"] == shard_id]
    require(len(matches) == 1, "UNKNOWN_HISTORY_SHARD")
    shard = matches[0]
    completed, failed, reused = [], [], []
    pending = []
    for symbol in shard["symbols"]:
        # Corrupt saved evidence is a blocker, never permission to reacquire over it.
        loaded = load_checkpoint(durable_root, plan, symbol, shard["market"])
        if loaded is not None:
            reused.append(symbol)
        else:
            pending.append(symbol)
    started = time.monotonic()
    responses = {}
    if pending:
        from .sources.twse import TWSEAdapter
        from .sources.tpex import TPExAdapter
        with tempfile.TemporaryDirectory(prefix="rate-history-owner-") as workspace:
            try:
                fundamentals = acquire_fundamentals(pending, shard["market"], plan, workspace, started,
                                                    evidence_root=output_root, authority=authority)
            except Exception as exc:
                return {"artifact": "RATE_HISTORY_SHARD_PROGRESS", "shard_id": shard_id, "plan_id": plan["plan_id"],
                        "validation_status": "FAIL_CLOSED", "completed_symbols": [], "reused_symbols": reused,
                        "failed_symbols": [{"symbol": s, "reason": str(exc), "scope": "MARKET_SOURCE"} for s in pending], "fallback_used": False}
            for symbol in pending:
                row_failures = fundamentals[symbol].get("failures", [])
                if row_failures:
                    failed.append({"symbol": symbol, "reason": row_failures[0]["reason"], "scope": "ROW",
                                   "fundamental_row_failures": row_failures})
                    continue
                try:
                    owner = TWSEAdapter() if shard["market"] == "TWSE" else TPExAdapter()
                    adapter = ReceiptAdapter(owner, started, contract()["max_shard_seconds"], responses)
                    material = acquire_symbol(symbol, shard["market"], plan, adapter, workspace, fundamentals[symbol], started)
                    material["acquisition_runtime_authority"] = authority
                    persist_symbol(output_root, material, plan, symbol, shard["market"])
                    completed.append(symbol)
                except Exception as exc:
                    failed.append({"symbol": symbol, "reason": str(exc)})
    return {"artifact": "RATE_HISTORY_SHARD_PROGRESS", "shard_id": shard_id, "plan_id": plan["plan_id"],
            "validation_status": "FAIL_CLOSED" if failed else "PASS", "completed_symbols": completed,
            "reused_symbols": reused, "failed_symbols": failed, "fallback_used": False}

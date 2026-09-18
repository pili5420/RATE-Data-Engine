"""Bounded, resumable TPEx monthly history bootstrap.

The TPEx product is a shared monthly response.  A period is requested once,
then the approved five-symbol universe is filtered locally.  Response
identity is checked before any row is admitted to the checkpoint; a current
snapshot returned for a historical request is a hard data-integrity failure.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import date, datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.build_live_source_bundle import _atomic_write_json, _month_cursor
from src.historical_store import _number
from src.sources.tpex import TPExAdapter, normalize_tpex_date

TPEx_SYMBOLS = ("6274", "3081", "6187", "6510", "3227")
TARGET_RAW_SESSIONS = 190
CHECKPOINT_SCHEMA = "RATE-TPEX-HISTORY-CHECKPOINT-V1"
SOURCE_DATASET = "TPEx Historical Data of Individual Mainboard Stock"


def _now():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _universe_digest():
    return hashlib.sha256(json.dumps(TPEx_SYMBOLS, separators=(",", ":")).encode()).hexdigest()


def _digest(obj):
    clean = {k: v for k, v in obj.items() if k not in ("content_hash", "last_updated")}
    return hashlib.sha256(json.dumps(clean, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _load(path: Path):
    if not path.exists():
        return {"schema_version": CHECKPOINT_SCHEMA, "universe_digest": _universe_digest(), "market": "TPEX", "source_dataset_version": SOURCE_DATASET, "months": {}, "content_hash": None, "last_updated": None}
    obj = json.loads(path.read_text(encoding="utf-8"))
    if obj.get("schema_version") != CHECKPOINT_SCHEMA or obj.get("universe_digest") != _universe_digest() or obj.get("market") != "TPEX" or obj.get("content_hash") != _digest(obj):
        raise RuntimeError("TPEX_HISTORY_CHECKPOINT_INVALID")
    return obj


def _save(path: Path, cp):
    cp["schema_version"] = CHECKPOINT_SCHEMA
    cp["universe_digest"] = _universe_digest()
    cp["market"] = "TPEX"
    cp["source_dataset_version"] = SOURCE_DATASET
    cp["last_updated"] = _now()
    cp["content_hash"] = _digest(cp)
    _atomic_write_json(path, cp)


def _as_number(value, field):
    if value in (None, "", "-", "--"):
        raise ValueError(f"MISSING:{field}")
    return _number(value, field)


def _period_matches(value: str, period: str) -> bool:
    return normalize_tpex_date(value)[:7] == f"{period[:4]}-{period[4:6]}"


def _row_from_dict(row, symbol, result):
    code = str(row.get("symbol") or row.get("SecuritiesCompanyCode") or row.get("Code") or "").strip()
    if code != symbol:
        return None
    raw_date = row.get("trade_date") or row.get("tradeDate") or row.get("Date") or row.get("日期")
    if raw_date is None:
        return None
    trade_date = normalize_tpex_date(raw_date)
    out = {
        "symbol": symbol, "market": "TPEX", "trade_date": trade_date,
        "open": _as_number(row.get("open", row.get("Open", row.get("開盤價"))), "open"),
        "high": _as_number(row.get("high", row.get("High", row.get("最高價"))), "high"),
        "low": _as_number(row.get("low", row.get("Low", row.get("最低價"))), "low"),
        "close": _as_number(row.get("close", row.get("Close", row.get("收盤價"))), "close"),
        "volume": _as_number(row.get("volume", row.get("TradingShares", row.get("成交股數"))), "volume"),
        "turnover": _as_number(row.get("turnover", row.get("TransactionAmount", row.get("成交金額"))), "turnover"),
        "source": "TPEX_HISTORICAL_STOCK", "source_timestamp": result.get("source_timestamp"),
        "ingested_at": result.get("retrieval_timestamp"),
    }
    return out


def extract_month_rows(result: dict, symbols, period: str):
    """Extract and normalize only approved symbols from one shared response."""
    payload = result.get("raw_payload")
    candidates = []
    if isinstance(payload, list):
        candidates = payload
    elif isinstance(payload, dict):
        # Page APIs return tables; retain the table date as an identity hint.
        tables = payload.get("tables") or []
        for table in tables:
            fields = table.get("fields") or []
            for row in table.get("data") or []:
                if isinstance(row, dict):
                    candidates.append(row)
                elif isinstance(row, list) and fields and len(fields) == len(row):
                    candidates.append(dict(zip(fields, row)))
        if not candidates and isinstance(payload.get("data"), list):
            candidates = payload["data"]
    normalized = []
    seen = set()
    for row in candidates:
        for symbol in symbols:
            try:
                item = _row_from_dict(row, symbol, result)
            except (TypeError, ValueError):
                continue
            if item is None:
                continue
            if not _period_matches(item["trade_date"], period):
                raise RuntimeError(f"TPEX_HISTORY_RESPONSE_IDENTITY_MISMATCH:{period}:{item['trade_date'][:7]}")
            key = (symbol, item["trade_date"])
            if key in seen:
                raise RuntimeError(f"TPEX_DUPLICATE_DATE:{symbol}:{item['trade_date']}")
            seen.add(key); normalized.append(item)
    # A historical response must expose date-bearing rows.  The current
    # daily-close snapshot has no historical dates and therefore fails closed.
    if not normalized:
        raise RuntimeError(f"TPEX_HISTORY_RESPONSE_IDENTITY_MISMATCH:{period}:NO_DATE_ROWS")
    today = date.today().isoformat()
    if any(row["trade_date"] > today for row in normalized):
        raise RuntimeError("TPEX_FUTURE_DATED_RECORD")
    return normalized


def _records_for_symbol(cp, symbol):
    by_date = {}
    for entry in cp.get("months", {}).values():
        if entry.get("market") != "TPEX" or entry.get("symbol_rows") is None:
            continue
        for row in entry.get("records", []):
            if row.get("symbol") == symbol:
                by_date[row["trade_date"]] = row
    return sorted(by_date.values(), key=lambda row: row["trade_date"])


def _write_evidence(output: Path, payload):
    _atomic_write_json(output, payload)
    return payload


def bootstrap(*, trading_date: str, checkpoint: Path, output: Path, max_months: int = 36, adapter=None):
    cp = _load(checkpoint)
    adapter = adapter or TPExAdapter()
    request_count = 0
    cache_hits = 0
    periods_used = []
    status = "FAIL"
    reason = None
    try:
        end = date.fromisoformat(trading_date)
        for index, period in enumerate(_month_cursor(end)):
            if index >= max_months:
                break
            periods_used.append(period)
            if all(len(_records_for_symbol(cp, symbol)) >= TARGET_RAW_SESSIONS for symbol in TPEx_SYMBOLS):
                break
            entry = cp.setdefault("months", {}).get(period)
            if isinstance(entry, dict) and entry.get("validation_status") == "PASS":
                cache_hits += 1
                continue
            # One shared response per month.  The first approved symbol is a
            # route argument only; rows for all five symbols are filtered here.
            result = adapter.fetch_historical_symbol(TPEx_SYMBOLS[0], period)
            request_count += 1
            records = extract_month_rows(result, TPEx_SYMBOLS, period)
            grouped = {symbol: [] for symbol in TPEx_SYMBOLS}
            for row in records:
                grouped[row["symbol"]].append(row)
            cp["months"][period] = {
                "period": period, "market": "TPEX", "provider": "TPEx Official",
                "dataset": SOURCE_DATASET, "symbol_rows": sorted(grouped),
                "records": records, "record_count": len(records),
                "source": result.get("endpoint"), "source_timestamp": result.get("source_timestamp"),
                "retrieval_timestamp": result.get("retrieval_timestamp"),
                "content_hash": hashlib.sha256(json.dumps(records, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
                "validation_status": "PASS",
            }
            _save(checkpoint, cp)
        counts = {symbol: len(_records_for_symbol(cp, symbol)) for symbol in TPEx_SYMBOLS}
        if not all(value >= TARGET_RAW_SESSIONS for value in counts.values()):
            raise RuntimeError("DATA_INCOMPLETE:TPEX_RAW_HISTORY:" + ",".join(f"{s}={counts[s]}" for s in TPEx_SYMBOLS))
        status = "PASS"
        payload = {
            "artifact": "RATE_TPEX_HISTORY_BOOTSTRAP_EVIDENCE", "status": status, "market": "TPEX",
            "symbols": list(TPEx_SYMBOLS), "universe_digest": _universe_digest(),
            "raw_sessions_by_symbol": counts, "raw_coverage": f"{sum(v >= TARGET_RAW_SESSIONS for v in counts.values())}/5",
            "raw_sessions_ge_190": f"{sum(v >= TARGET_RAW_SESSIONS for v in counts.values())}/5",
            "monthly_periods_fetched": sorted(cp.get("months", {}).keys()),
            "monthly_periods_used_this_run": periods_used, "monthly_request_count": request_count,
            "monthly_cache_hits": cache_hits, "monthly_request_deduplication": "PASS",
            "checkpoint_content_hash": cp.get("content_hash"), "validation_status": "PASS",
            "source_dataset": SOURCE_DATASET, "production_state_modified": "NO", "generated_at": _now(),
        }
    except Exception as exc:
        reason = str(exc)
        counts = {symbol: len(_records_for_symbol(cp, symbol)) for symbol in TPEx_SYMBOLS}
        payload = {
            "artifact": "RATE_TPEX_HISTORY_BOOTSTRAP_EVIDENCE", "status": "FAIL", "market": "TPEX",
            "symbols": list(TPEx_SYMBOLS), "universe_digest": _universe_digest(),
            "raw_sessions_by_symbol": counts, "raw_coverage": f"{sum(v > 0 for v in counts.values())}/5",
            "raw_sessions_ge_190": f"{sum(v >= TARGET_RAW_SESSIONS for v in counts.values())}/5",
            "monthly_periods_fetched": sorted(cp.get("months", {}).keys()),
            "monthly_periods_used_this_run": periods_used, "monthly_request_count": request_count,
            "monthly_cache_hits": cache_hits, "monthly_request_deduplication": "PASS" if request_count <= len(set(periods_used)) else "FAIL",
            "checkpoint_content_hash": cp.get("content_hash"), "validation_status": "FAIL",
            "blocking_reason": reason, "source_dataset": SOURCE_DATASET, "production_state_modified": "NO", "generated_at": _now(),
        }
    _write_evidence(output, payload)
    return payload


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--trading-date", required=True)
    ap.add_argument("--checkpoint", default="data/staging/history_bootstrap/RATE_TPEX_HISTORY_CHECKPOINT_V1.json")
    ap.add_argument("--output", default="artifacts/RATE_TPEX_HISTORY_BOOTSTRAP_EVIDENCE.json")
    ap.add_argument("--max-months", type=int, default=36)
    args = ap.parse_args()
    result = bootstrap(trading_date=args.trading_date, checkpoint=Path(args.checkpoint), output=Path(args.output), max_months=args.max_months)
    print(json.dumps({"status": result["status"], "raw_coverage": result["raw_coverage"], "request_count": result["monthly_request_count"]}))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())

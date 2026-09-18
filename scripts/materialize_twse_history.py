"""Materialize the accepted TWSE bootstrap checkpoint into canonical staging.

This command is intentionally offline with respect to stock history.  The
checkpoint is the recovery/provenance authority; the JSON files written under
``data/staging/history/market_daily`` are the runtime historical input.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from datetime import date, datetime, timezone
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.build_live_source_bundle import _atomic_write_json, validate_checkpoint
from src.historical_store import MAX_SESSIONS, PersistentHistoricalStore

EXPECTED_CHECKPOINT_DIGEST = "4202253573c3feb61bd9994dac04b9a1f96155071575ae4d2f2ec1f9efb31e3f"
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _digest(records):
    return hashlib.sha256(json.dumps(records, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _symbols(universe_path: Path):
    obj = json.loads(universe_path.read_text(encoding="utf-8"))
    entries = obj.get("symbols", [])
    twse = [str(x["symbol"]) for x in entries if x.get("market") == "TWSE"]
    if len(twse) != 25 or len(set(twse)) != 25:
        raise RuntimeError("INVALID_PRODUCTION_UNIVERSE_AUTHORITY:TWSE_SYMBOL_COUNT")
    return twse, {str(x["symbol"]) for x in entries if x.get("market") == "TPEX"}


def _validate_record(record, symbol):
    if record.get("symbol") != symbol or record.get("market") != "TWSE":
        raise RuntimeError(f"TWSE_MATERIALIZATION_MARKET_OR_SYMBOL_MISMATCH:{symbol}")
    trade_date = str(record.get("trade_date", ""))
    if not DATE_RE.match(trade_date) or trade_date > date.today().isoformat():
        raise RuntimeError(f"TWSE_MATERIALIZATION_INVALID_DATE:{symbol}:{trade_date}")
    values = [record.get(name) for name in ("open", "high", "low", "close", "volume", "turnover")]
    if any(value is None or not math.isfinite(float(value)) for value in values):
        raise RuntimeError(f"TWSE_MATERIALIZATION_INVALID_OHLCV:{symbol}:{trade_date}")
    opening, high, low, close, volume, turnover = map(float, values)
    if min(opening, high, low, close) <= 0 or volume < 0 or turnover < 0:
        raise RuntimeError(f"TWSE_MATERIALIZATION_RANGE_FAILURE:{symbol}:{trade_date}")
    if high < max(opening, close) or low > min(opening, close):
        raise RuntimeError(f"TWSE_MATERIALIZATION_OHLC_FAILURE:{symbol}:{trade_date}")


def materialize(*, checkpoint: Path, universe_file: Path, history_root: Path, output: Path,
                expected_checkpoint_digest: str = EXPECTED_CHECKPOINT_DIGEST):
    universe_obj = json.loads(universe_file.read_text(encoding="utf-8"))
    universe_digest = universe_obj.get("universe_symbol_digest")
    if not universe_digest:
        raise RuntimeError("INVALID_PRODUCTION_UNIVERSE_AUTHORITY")
    checked = validate_checkpoint(checkpoint, universe_digest)
    checkpoint_obj = checked["checkpoint"]
    if checkpoint_obj.get("content_hash") != expected_checkpoint_digest:
        raise RuntimeError("TWSE_ACCEPTED_CHECKPOINT_IDENTITY_MISMATCH")
    twse_symbols, tpex_symbols = _symbols(universe_file)
    by_symbol = {symbol: [] for symbol in twse_symbols}
    for entry in checkpoint_obj.get("months", {}).values():
        if not isinstance(entry, dict) or entry.get("market") != "TWSE":
            continue
        symbol = str(entry.get("symbol", ""))
        if symbol in by_symbol:
            by_symbol[symbol].extend(entry.get("records", []))
    store = PersistentHistoricalStore(history_root)
    symbol_evidence = {}
    for symbol in twse_symbols:
        records = sorted(by_symbol[symbol], key=lambda row: row.get("trade_date", ""))
        seen = set()
        for record in records:
            _validate_record(record, symbol)
            key = record["trade_date"]
            if key in seen:
                raise RuntimeError(f"TWSE_MATERIALIZATION_DUPLICATE_DATE:{symbol}:{key}")
            seen.add(key)
        if len(records) < 180:
            raise RuntimeError(f"DATA_INCOMPLETE:TWSE_MATERIALIZED_HISTORY:{symbol}")
        expected_retained = records[-MAX_SESSIONS:]
        result = store.materialize_stock(symbol, records)
        persisted = store.load_stock(symbol)
        checkpoint_digest = _digest(records)
        retained_digest = _digest(expected_retained)
        store_digest = _digest(persisted)
        if persisted != expected_retained or store_digest != retained_digest:
            raise RuntimeError(f"TWSE_MATERIALIZATION_CONTENT_IDENTITY_FAILURE:{symbol}")
        symbol_evidence[symbol] = {
            "symbol": symbol,
            "market": "TWSE",
            "checkpoint_raw_sessions": len(records),
            "persisted_store_sessions": len(persisted),
            "trimmed_old_sessions": len(records) - len(persisted),
            "checkpoint_normalized_record_digest": checkpoint_digest,
            "materialized_store_digest": store_digest,
            "content_identity_status": "PASS",
            "earliest_trade_date": persisted[0]["trade_date"],
            "latest_trade_date": persisted[-1]["trade_date"],
            "source": "TWSE_STOCK_DAY",
        }
    contamination = 0
    market_dir = history_root / "market_daily"
    for path in market_dir.glob("*.json"):
        try:
            rows = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            contamination += 1
            continue
        for row in rows if isinstance(rows, list) else []:
            if row.get("market") != "TWSE" or str(row.get("symbol")) in tpex_symbols:
                contamination += 1
    if contamination:
        raise RuntimeError(f"CROSS_MARKET_CONTAMINATION:{contamination}")
    payload = {
        "artifact": "RATE_TWSE_HISTORY_MATERIALIZATION_EVIDENCE",
        "status": "PASS",
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "accepted_checkpoint_digest": expected_checkpoint_digest,
        "materialized_source_checkpoint_digest": checkpoint_obj.get("content_hash"),
        "checkpoint_restore_identity": "PASS",
        "twse_network_requests_for_stock_backfill": 0,
        "symbols_materialized": len(symbol_evidence),
        "checkpoint_sessions_by_symbol": {s: d["checkpoint_raw_sessions"] for s, d in symbol_evidence.items()},
        "store_sessions_by_symbol": {s: d["persisted_store_sessions"] for s, d in symbol_evidence.items()},
        "trimmed_sessions_by_symbol": {s: d["trimmed_old_sessions"] for s, d in symbol_evidence.items()},
        "store_digest_by_symbol": {s: d["materialized_store_digest"] for s, d in symbol_evidence.items()},
        "content_identity_status": f"{sum(d['content_identity_status'] == 'PASS' for d in symbol_evidence.values())}/25 PASS",
        "cross_market_contamination": contamination,
        "store_provenance_binding": "PASS" if checkpoint_obj.get("content_hash") == expected_checkpoint_digest else "FAIL",
        "symbols": symbol_evidence,
        "retention_max_sessions": MAX_SESSIONS,
        "production_state_modified": "NO",
    }
    _atomic_write_json(output, payload)
    return payload


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--checkpoint", required=True)
    ap.add_argument("--universe-file", required=True)
    ap.add_argument("--history-root", default="data/staging/history")
    ap.add_argument("--output", default="artifacts/RATE_TWSE_HISTORY_MATERIALIZATION_EVIDENCE.json")
    ap.add_argument("--expected-checkpoint-digest", default=EXPECTED_CHECKPOINT_DIGEST)
    args = ap.parse_args()
    try:
        result = materialize(checkpoint=Path(args.checkpoint), universe_file=Path(args.universe_file), history_root=Path(args.history_root), output=Path(args.output), expected_checkpoint_digest=args.expected_checkpoint_digest)
        print(json.dumps({"status": result["status"], "symbols_materialized": result["symbols_materialized"]}))
        return 0
    except Exception as exc:
        print(json.dumps({"status": "FAIL", "reason": str(exc)}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

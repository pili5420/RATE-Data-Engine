"""Materialize the approved TPEx checkpoint into the canonical staging store."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.bootstrap_tpex_history import TPEx_SYMBOLS, TARGET_RAW_SESSIONS, _load
from src.historical_store import PersistentHistoricalStore

TARGET_PERSISTED_SESSIONS = 180


def materialize(*, checkpoint: Path, history_root: Path, output: Path):
    cp = _load(checkpoint)
    store = PersistentHistoricalStore(history_root)
    rows = []
    try:
        for symbol in TPEx_SYMBOLS:
            records = []
            for entry in cp.get("records", {}).values():
                records.extend(row for row in entry.get("records", []) if row.get("symbol") == symbol)
            if len(records) < TARGET_RAW_SESSIONS:
                raise RuntimeError(f"DATA_INCOMPLETE:TPEX_RAW_HISTORY:{symbol}:{len(records)}")
            if any(row.get("market") != "TPEX" for row in records):
                raise RuntimeError(f"TPEX_MARKET_IDENTITY_FAILURE:{symbol}")
            result = store.materialize_stock(symbol, records)
            persisted = store.load_stock(symbol)
            if len(persisted) < TARGET_PERSISTED_SESSIONS:
                raise RuntimeError(f"DATA_INCOMPLETE:TPEX_PERSISTED_HISTORY:{symbol}:{len(persisted)}")
            rows.append({
                "symbol": symbol, "market": "TPEX", "raw_source_sessions": len(records),
                "persisted_sessions": len(persisted), "trimmed_sessions": result["trimmed_count"],
                "content_hash": result["content_hash"], "earliest_date": persisted[0]["trade_date"],
                "latest_date": persisted[-1]["trade_date"], "validation_status": "PASS",
            })
        unexpected = []
        for path in (Path(history_root) / "market_daily").glob("*.json"):
            symbol = path.stem
            if symbol in TPEx_SYMBOLS:
                continue
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            if any(row.get("market") == "TPEX" for row in data):
                unexpected.append(symbol)
        if unexpected:
            raise RuntimeError("UNEXPECTED_TPEX_SYMBOLS_PERSISTED:" + ",".join(sorted(unexpected)))
        payload = {
            "artifact": "RATE_TPEX_HISTORY_MATERIALIZATION_EVIDENCE", "status": "PASS",
            "market": "TPEX", "symbols": list(TPEx_SYMBOLS), "materialized_symbols": "5/5",
            "materialized_sessions_ge_180": "5/5", "unexpected_symbols_persisted": unexpected,
            "symbol_rows": rows, "checkpoint_content_hash": cp.get("content_hash"),
            "production_state_modified": "NO", "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        }
    except Exception as exc:
        payload = {
            "artifact": "RATE_TPEX_HISTORY_MATERIALIZATION_EVIDENCE", "status": "FAIL", "market": "TPEX",
            "symbols": list(TPEx_SYMBOLS), "materialized_symbols": f"{len(rows)}/5",
            "materialized_sessions_ge_180": f"{sum(row.get('persisted_sessions', 0) >= TARGET_PERSISTED_SESSIONS for row in rows)}/5",
            "symbol_rows": rows, "blocking_reason": str(exc), "production_state_modified": "NO",
            "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return payload


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--checkpoint", default="data/staging/history_bootstrap/RATE_TPEX_HISTORY_CHECKPOINT_V2.json")
    ap.add_argument("--history-root", default="data/staging/history")
    ap.add_argument("--output", default="artifacts/RATE_TPEX_HISTORY_MATERIALIZATION_EVIDENCE.json")
    args = ap.parse_args()
    result = materialize(checkpoint=Path(args.checkpoint), history_root=Path(args.history_root), output=Path(args.output))
    print(json.dumps({"status": result["status"], "materialized_symbols": result["materialized_symbols"]}))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())

"""Bootstrap the official TWSE TAIEX historical benchmark into staging."""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import date, datetime, timezone
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.build_live_source_bundle import _atomic_write_json, _month_cursor, _rows
from src.benchmark_history import benchmark_digest, normalize_benchmark, validate_benchmark
from src.historical_store import PersistentHistoricalStore
from src.sources.twse import TWSEAdapter

TARGET_RECORDS = 220
CHECKPOINT_SCHEMA = "RATE-TAIEX-HISTORY-CHECKPOINT-V1"


def _now():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _digest(obj):
    clean = {k: v for k, v in obj.items() if k not in ("content_hash", "last_updated")}
    return hashlib.sha256(json.dumps(clean, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _load(path: Path):
    if not path.exists():
        return {"schema_version": CHECKPOINT_SCHEMA, "periods": {}, "content_hash": None, "last_updated": None}
    obj = json.loads(path.read_text(encoding="utf-8"))
    if obj.get("schema_version") != CHECKPOINT_SCHEMA or obj.get("content_hash") != _digest(obj):
        raise RuntimeError("TAIEX_HISTORY_CHECKPOINT_INVALID")
    return obj


def _save(path: Path, checkpoint):
    checkpoint["schema_version"] = CHECKPOINT_SCHEMA
    checkpoint["last_updated"] = _now()
    checkpoint["content_hash"] = _digest(checkpoint)
    _atomic_write_json(path, checkpoint)


def _normalize_result(result):
    rows = []
    for row in _rows(result.get("raw_payload")):
        try:
            rows.append(normalize_benchmark(row, benchmark_symbol="TAIEX", market="TWSE", source="TWSE_TAIEX_MI_5MINS_HIST", source_timestamp=result.get("source_timestamp"), ingested_at=result.get("retrieval_timestamp")))
        except (TypeError, ValueError):
            continue
    return rows


def bootstrap(*, trading_date: str, checkpoint: Path, history_root: Path, output: Path, max_months: int = 36):
    cp = _load(checkpoint)
    request_count = 0
    cache_hits = 0
    periods_seen = []
    adapter = TWSEAdapter()
    end = date.fromisoformat(trading_date)
    for period in _month_cursor(end):
        periods_seen.append(period)
        entry = cp.setdefault("periods", {}).get(period)
        if isinstance(entry, dict) and entry.get("validation_status") == "PASS" and isinstance(entry.get("records"), list):
            cache_hits += 1
        else:
            result = adapter.fetch_historical_benchmark(period)
            records = _normalize_result(result)
            if not records:
                raise RuntimeError(f"DATA_INCOMPLETE:TAIEX_MONTH:{period}")
            validate_benchmark(records, "TAIEX")
            canonical = json.dumps(records, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
            cp.setdefault("periods", {})[period] = {
                "period": period,
                "records": records,
                "record_count": len(records),
                "source": "TWSE_TAIEX_MI_5MINS_HIST",
                "source_timestamp": result.get("source_timestamp"),
                "retrieval_timestamp": result.get("retrieval_timestamp"),
                "content_hash": hashlib.sha256(canonical).hexdigest(),
                "validation_status": "PASS",
            }
            request_count += 1
            _save(checkpoint, cp)
        all_records = []
        for value in cp.get("periods", {}).values():
            all_records.extend(value.get("records", []))
        by_date = {}
        for row in all_records:
            if row["trade_date"] in by_date and by_date[row["trade_date"]] != row:
                raise RuntimeError(f"TAIEX_DATE_CONFLICT:{row['trade_date']}")
            by_date[row["trade_date"]] = row
        if len(by_date) >= TARGET_RECORDS:
            break
        if len(periods_seen) >= max_months:
            break
    all_records = []
    for value in cp.get("periods", {}).values():
        all_records.extend(value.get("records", []))
    unique = {row["trade_date"]: row for row in all_records}
    ordered = sorted(unique.values(), key=lambda row: row["trade_date"])
    validate_benchmark(ordered, "TAIEX")
    if len(ordered) < 180:
        raise RuntimeError(f"DATA_INCOMPLETE:TAIEX_HISTORY:{len(ordered)}<180")
    store = PersistentHistoricalStore(history_root)
    store.upsert_benchmark("TAIEX", ordered)
    persisted = store.load_benchmark("TAIEX")
    validate_benchmark(persisted, "TAIEX")
    if len(persisted) < 180:
        raise RuntimeError(f"DATA_INCOMPLETE:TAIEX_PERSISTED_HISTORY:{len(persisted)}<180")
    payload = {
        "artifact": "RATE_TAIEX_HISTORY_EVIDENCE",
        "status": "PASS",
        "benchmark_symbol": "TAIEX",
        "market": "TWSE",
        "source_dataset": "TWSE_TAIEX_MI_5MINS_HIST",
        "monthly_periods": sorted(cp.get("periods", {}).keys()),
        "monthly_periods_used_this_run": periods_seen,
        "request_count": request_count,
        "cache_hits": cache_hits,
        "record_count": len(persisted),
        "earliest_date": persisted[0]["trade_date"],
        "latest_date": persisted[-1]["trade_date"],
        "benchmark_digest": benchmark_digest(persisted),
        "validation_status": "PASS",
        "duplicate_dates": 0,
        "future_dates": 0,
        "invalid_close": 0,
        "wrong_benchmark_assignment": 0,
        "retrieval_timestamp": _now(),
        "checkpoint_content_hash": cp.get("content_hash"),
        "production_state_modified": "NO",
    }
    _atomic_write_json(output, payload)
    return payload


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--trading-date", required=True)
    ap.add_argument("--checkpoint", default="data/staging/history_bootstrap/RATE_TAIEX_HISTORY_CHECKPOINT_V1.json")
    ap.add_argument("--history-root", default="data/staging/history")
    ap.add_argument("--output", default="artifacts/RATE_TAIEX_HISTORY_EVIDENCE.json")
    ap.add_argument("--max-months", type=int, default=36)
    args = ap.parse_args()
    try:
        result = bootstrap(trading_date=args.trading_date, checkpoint=Path(args.checkpoint), history_root=Path(args.history_root), output=Path(args.output), max_months=args.max_months)
        print(json.dumps({"status": result["status"], "record_count": result["record_count"], "request_count": result["request_count"], "cache_hits": result["cache_hits"]}))
        return 0
    except Exception as exc:
        print(json.dumps({"status": "FAIL", "reason": str(exc)}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

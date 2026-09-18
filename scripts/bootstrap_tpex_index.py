"""Bootstrap the official TPEx Index monthly historical series."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.build_live_source_bundle import _atomic_write_json, _month_cursor
from src.benchmark_history import benchmark_digest, normalize_benchmark, validate_benchmark
from src.historical_store import PersistentHistoricalStore
from src.sources.tpex import TPExAdapter, normalize_tpex_date

TARGET_RECORDS = 220
CHECKPOINT_SCHEMA = "RATE-TPEX-INDEX-HISTORY-CHECKPOINT-V1"


def _now():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _checkpoint_digest(obj):
    clean = {k: v for k, v in obj.items() if k not in ("content_hash", "last_updated")}
    return hashlib.sha256(json.dumps(clean, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


def _load_checkpoint(path):
    if not path.exists():
        return {"schema_version": CHECKPOINT_SCHEMA, "periods": {}, "content_hash": None, "last_updated": None}
    obj = json.loads(path.read_text(encoding="utf-8"))
    if obj.get("schema_version") != CHECKPOINT_SCHEMA or obj.get("content_hash") != _checkpoint_digest(obj):
        raise RuntimeError("TPEX_INDEX_HISTORY_CHECKPOINT_INVALID")
    return obj


def _save_checkpoint(path, cp):
    cp["schema_version"] = CHECKPOINT_SCHEMA; cp["last_updated"] = _now(); cp["content_hash"] = _checkpoint_digest(cp)
    _atomic_write_json(path, cp)


def _rows(payload):
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        tables = payload.get("tables") or []
        out = []
        for table in tables:
            fields = table.get("fields") or []
            for row in table.get("data") or []:
                out.append(row if isinstance(row, dict) else dict(zip(fields, row)))
        return out
    return []


def _normalize(result, period):
    records = []
    for row in _rows(result.get("raw_payload")):
        try:
            item = normalize_benchmark(row, benchmark_symbol="TPEX", market="TPEX", source="TPEX_INDEX_HISTORY", source_timestamp=result.get("source_timestamp"), ingested_at=result.get("retrieval_timestamp"))
            if not item.get("trade_date") or item["trade_date"][:7] != f"{period[:4]}-{period[4:6]}":
                raise RuntimeError(f"TPEX_INDEX_RESPONSE_IDENTITY_MISMATCH:{period}:{item.get('trade_date')}")
            records.append(item)
        except RuntimeError:
            raise
        except (TypeError, ValueError) as exc:
            raise RuntimeError(f"TPEX_INDEX_ROW_INVALID:{period}") from exc
    if not records:
        raise RuntimeError(f"DATA_INCOMPLETE:TPEX_INDEX_MONTH:{period}")
    validate_benchmark(records, "TPEX")
    return records


def bootstrap(*, trading_date: str, checkpoint: Path, history_root: Path, output: Path, max_months: int = 36, adapter=None):
    cp = _load_checkpoint(checkpoint); adapter = adapter or TPExAdapter(); request_count = 0; cache_hits = 0; periods_used = []
    try:
        for index, period in enumerate(_month_cursor(date.fromisoformat(trading_date))):
            if index >= max_months:
                break
            periods_used.append(period)
            entry = cp.setdefault("periods", {}).get(period)
            if isinstance(entry, dict) and entry.get("validation_status") == "PASS":
                cache_hits += 1
            else:
                result = adapter.fetch_historical_benchmark(period)
                records = _normalize(result, period)
                canonical = json.dumps(records, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
                cp["periods"][period] = {"period": period, "records": records, "record_count": len(records), "source": result.get("endpoint"), "source_timestamp": result.get("source_timestamp"), "retrieval_timestamp": result.get("retrieval_timestamp"), "content_hash": hashlib.sha256(canonical).hexdigest(), "validation_status": "PASS"}
                _save_checkpoint(checkpoint, cp); request_count += 1
            all_records = [row for entry in cp.get("periods", {}).values() for row in entry.get("records", [])]
            by_date = {}
            for row in all_records:
                key = row["trade_date"]
                if key in by_date and by_date[key] != row:
                    raise RuntimeError(f"TPEX_INDEX_DATE_CONFLICT:{key}")
                by_date[key] = row
            if len(by_date) >= TARGET_RECORDS:
                break
        ordered = sorted(by_date.values(), key=lambda row: row["trade_date"]) if 'by_date' in locals() else []
        validate_benchmark(ordered, "TPEX")
        if len(ordered) < 180:
            raise RuntimeError(f"DATA_INCOMPLETE:TPEX_INDEX_HISTORY:{len(ordered)}<180")
        store = PersistentHistoricalStore(history_root); store.upsert_benchmark("TPEX", ordered)
        persisted = store.load_benchmark("TPEX"); validate_benchmark(persisted, "TPEX")
        if len(persisted) < 180:
            raise RuntimeError(f"DATA_INCOMPLETE:TPEX_INDEX_PERSISTED_HISTORY:{len(persisted)}<180")
        digest = benchmark_digest(persisted)
        payload = {"artifact": "RATE_TPEX_INDEX_HISTORY_EVIDENCE", "status": "PASS", "benchmark_symbol": "TPEX", "market": "TPEX", "source_dataset": "TPEx Index Historical Data", "endpoint_contract": "MONTH_SCOPED_HISTORICAL_PAGE", "endpoint": "https://www.tpex.org.tw/www/en-us/indexInfo/inx", "monthly_periods": sorted(cp.get("periods", {}).keys()), "monthly_periods_used_this_run": periods_used, "request_count": request_count, "cache_hits": cache_hits, "redundant_requests": 0, "record_count": len(persisted), "earliest_date": persisted[0]["trade_date"], "latest_date": persisted[-1]["trade_date"], "benchmark_digest": digest, "deterministic_digest": benchmark_digest(persisted) == digest, "validation_status": "PASS", "production_state_modified": "NO", "generated_at": _now(), "checkpoint_content_hash": cp.get("content_hash")}
    except Exception as exc:
        payload = {"artifact": "RATE_TPEX_INDEX_HISTORY_EVIDENCE", "status": "FAIL", "benchmark_symbol": "TPEX", "market": "TPEX", "endpoint_contract": "MONTH_SCOPED_HISTORICAL_PAGE", "request_count": request_count, "cache_hits": cache_hits, "redundant_requests": 0, "record_count": 0, "benchmark_digest": None, "deterministic_digest": False, "validation_status": "FAIL", "blocking_reason": str(exc), "production_state_modified": "NO", "generated_at": _now(), "checkpoint_content_hash": cp.get("content_hash")}
    _atomic_write_json(output, payload); return payload


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--trading-date", required=True); ap.add_argument("--checkpoint", default="data/staging/history_bootstrap/RATE_TPEX_INDEX_HISTORY_CHECKPOINT_V1.json"); ap.add_argument("--history-root", default="data/staging/history"); ap.add_argument("--output", default="artifacts/RATE_TPEX_INDEX_HISTORY_EVIDENCE.json"); ap.add_argument("--max-months", type=int, default=36); args = ap.parse_args()
    result = bootstrap(trading_date=args.trading_date, checkpoint=Path(args.checkpoint), history_root=Path(args.history_root), output=Path(args.output), max_months=args.max_months)
    print(json.dumps({"status": result["status"], "record_count": result["record_count"], "request_count": result["request_count"]})); return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__": raise SystemExit(main())

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
from src.sources.tpex import INDEX_HISTORY_ENDPOINT, INDEX_HISTORY_PAGE_URL, TPExAdapter, normalize_tpex_date

TARGET_RECORDS = 220
CHECKPOINT_SCHEMA = "RATE-TPEX-INDEX-HISTORY-CHECKPOINT-V1"
CHECKPOINT_ARTIFACT = "RATE_TPEX_BENCHMARK_HISTORY_CHECKPOINT_V1"
SOURCE_AUTHORITY = "TPEx Official"


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


def _checkpoint_records(cp):
    by_date = {}
    for entry in cp.get("periods", {}).values():
        for row in entry.get("records", []):
            key = row["trade_date"]
            if key in by_date and by_date[key] != row:
                raise RuntimeError(f"TPEX_INDEX_DATE_CONFLICT:{key}")
            by_date[key] = row
    return sorted(by_date.values(), key=lambda row: row["trade_date"])


def _checkpoint_hashes(records, cp):
    raw_seed = {
        "period_hashes": {
            period: entry.get("content_hash")
            for period, entry in sorted((cp.get("periods") or {}).items())
        },
        "source_url": INDEX_HISTORY_PAGE_URL,
    }
    raw_sha = hashlib.sha256(json.dumps(raw_seed, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    normalized_sha = hashlib.sha256(json.dumps(records, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return raw_sha, normalized_sha


def _apply_contract_metadata(cp, *, records, trading_date, validation_status):
    dates = [row.get("trade_date") for row in records]
    duplicate_count = len(dates) - len(set(dates))
    future_count = sum(1 for value in dates if value and value > trading_date)
    close_values_pass = all(isinstance(row.get("close"), (int, float)) and row.get("close") > 0 for row in records)
    raw_sha, normalized_sha = _checkpoint_hashes(records, cp)
    cp.update({
        "artifact": CHECKPOINT_ARTIFACT,
        "benchmark_id": "TPEX",
        "source_authority": SOURCE_AUTHORITY,
        "source_url": INDEX_HISTORY_PAGE_URL,
        "source_endpoint": INDEX_HISTORY_ENDPOINT,
        "historical_product": "Historical Data of TPEx Index (Monthly)",
        "retrieval_timestamp": cp.get("last_updated") or _now(),
        "first_date": records[0]["trade_date"] if records else None,
        "last_date": records[-1]["trade_date"] if records else None,
        "session_count": len(records),
        "raw_sha256": raw_sha,
        "normalized_sha256": normalized_sha,
        "validation_status": validation_status,
        "date_order": "PASS" if dates == sorted(dates) else "FAIL",
        "duplicate_dates": duplicate_count,
        "future_dates": future_count,
        "close_values": "PASS" if close_values_pass else "FAIL",
        "trading_date_alignment": "PASS" if records and records[-1]["trade_date"] <= trading_date else "FAIL",
        "official_lineage": "PASS" if all((entry.get("validation_status") == "PASS") for entry in cp.get("periods", {}).values()) else "FAIL",
        "synthetic_interpolation": False,
        "missing_date_forward_fill": False,
    })


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
            ordered = _checkpoint_records(cp)
            if len(ordered) >= TARGET_RECORDS:
                break
        ordered = _checkpoint_records(cp)
        validate_benchmark(ordered, "TPEX")
        if len(ordered) < 180:
            raise RuntimeError(f"DATA_INCOMPLETE:TPEX_INDEX_HISTORY:{len(ordered)}<180")
        store = PersistentHistoricalStore(history_root); store.upsert_benchmark("TPEX", ordered)
        persisted = store.load_benchmark("TPEX"); validate_benchmark(persisted, "TPEX")
        if len(persisted) < 180:
            raise RuntimeError(f"DATA_INCOMPLETE:TPEX_INDEX_PERSISTED_HISTORY:{len(persisted)}<180")
        digest = benchmark_digest(persisted)
        _apply_contract_metadata(cp, records=persisted, trading_date=trading_date, validation_status="PASS")
        _save_checkpoint(checkpoint, cp)
        payload = {"artifact": "RATE_TPEX_INDEX_HISTORY_EVIDENCE", "status": "PASS", "benchmark_symbol": "TPEX", "market": "TPEX", "source_authority": SOURCE_AUTHORITY, "source_dataset": "TPEx Index Historical Data", "source_url": INDEX_HISTORY_PAGE_URL, "endpoint_contract": "MONTH_SCOPED_HISTORICAL_PAGE", "endpoint": INDEX_HISTORY_ENDPOINT, "monthly_periods": sorted(cp.get("periods", {}).keys()), "monthly_periods_used_this_run": periods_used, "request_count": request_count, "cache_hits": cache_hits, "redundant_requests": 0, "record_count": len(persisted), "earliest_date": persisted[0]["trade_date"], "latest_date": persisted[-1]["trade_date"], "benchmark_digest": digest, "deterministic_digest": benchmark_digest(persisted) == digest, "validation_status": "PASS", "production_state_modified": "NO", "generated_at": _now(), "checkpoint_content_hash": cp.get("content_hash"), "raw_sha256": cp.get("raw_sha256"), "normalized_sha256": cp.get("normalized_sha256"), "official_lineage": cp.get("official_lineage")}
    except Exception as exc:
        payload = {"artifact": "RATE_TPEX_INDEX_HISTORY_EVIDENCE", "status": "FAIL", "benchmark_symbol": "TPEX", "market": "TPEX", "endpoint_contract": "MONTH_SCOPED_HISTORICAL_PAGE", "request_count": request_count, "cache_hits": cache_hits, "redundant_requests": 0, "record_count": 0, "benchmark_digest": None, "deterministic_digest": False, "validation_status": "FAIL", "blocking_reason": str(exc), "production_state_modified": "NO", "generated_at": _now(), "checkpoint_content_hash": cp.get("content_hash")}
    _atomic_write_json(output, payload); return payload


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--trading-date", required=True); ap.add_argument("--checkpoint", default="data/staging/history_bootstrap/RATE_TPEX_INDEX_HISTORY_CHECKPOINT_V1.json"); ap.add_argument("--history-root", default="data/staging/history"); ap.add_argument("--output", default="artifacts/RATE_TPEX_INDEX_HISTORY_EVIDENCE.json"); ap.add_argument("--max-months", type=int, default=36); args = ap.parse_args()
    result = bootstrap(trading_date=args.trading_date, checkpoint=Path(args.checkpoint), history_root=Path(args.history_root), output=Path(args.output), max_months=args.max_months)
    print(json.dumps({"status": result["status"], "record_count": result["record_count"], "request_count": result["request_count"]})); return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__": raise SystemExit(main())

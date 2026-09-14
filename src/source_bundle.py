from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping

REQUIRED_FIELDS = {
    "symbol", "market_date", "as_of_timestamp", "source_timestamp", "trading_status",
    "price", "volume", "ma20", "ma60", "ma120", "momentum", "relative_strength",
    "foreign_flow", "investment_trust_flow", "large_holder_structure", "smart_money_flow",
    "fundamental_score", "liquidity",
}
NUMERIC_FIELDS = REQUIRED_FIELDS - {"symbol", "market_date", "as_of_timestamp", "source_timestamp", "trading_status"}

class SourceBundleError(ValueError):
    pass

def _canonical_bytes(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")

def create_input_snapshot_id(bundle_dir: str | Path, manifest: Mapping[str, object]) -> str:
    """Create a reproducible ID from manifest metadata and exact source file bytes."""
    root = Path(bundle_dir)
    digest = hashlib.sha256()
    digest.update(_canonical_bytes(manifest))
    for entry in sorted(manifest.get("files", []), key=lambda item: str(item["path"])):
        path = root / str(entry["path"])
        if not path.is_file():
            raise SourceBundleError(f"DATA_SOURCE_UNAVAILABLE:{entry['path']}")
        digest.update(str(entry["path"]).encode())
        digest.update(path.read_bytes())
    return "rate-snapshot-" + digest.hexdigest()[:24]

def load_bundle(bundle_dir: str | Path) -> tuple[dict, list[dict]]:
    root = Path(bundle_dir)
    manifest_path = root / "manifest.json"
    if not manifest_path.is_file():
        raise SourceBundleError("DATA_SOURCE_UNAVAILABLE:manifest.json")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("bundle_version") != "RATE-PRODUCTION-SOURCE-V1":
        raise SourceBundleError("SCHEMA_VALIDATION:bundle_version")
    snapshot_id = create_input_snapshot_id(root, manifest)
    records: list[dict] = []
    for entry in manifest.get("files", []):
        path = root / str(entry["path"])
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, list):
            raise SourceBundleError(f"TYPE_VALIDATION:{entry['path']}")
        records.extend(payload)
    return {**manifest, "input_snapshot_id": snapshot_id}, records

def validate_records(records: list[Mapping[str, object]], *, input_snapshot_id: str) -> list[str]:
    errors: list[str] = []
    seen: set[tuple] = set()
    for index, row in enumerate(records):
        missing = sorted(REQUIRED_FIELDS - row.keys())
        if missing:
            errors.append(f"MISSING_REQUIRED_DATA:row={index}:{','.join(missing)}")
            continue
        for field in NUMERIC_FIELDS:
            if type(row[field]) not in (int, float) or not 0 <= float(row[field]) <= 100:
                errors.append(f"RANGE_OR_TYPE:row={index}:{field}")
        if row["trading_status"] not in {"OPEN", "SUSPENDED", "HALTED", "DELISTED"}:
            errors.append(f"TYPE_VALIDATION:row={index}:trading_status")
        key = (row["symbol"], row["market_date"], row["as_of_timestamp"], input_snapshot_id)
        if key in seen:
            errors.append(f"DUPLICATE_CONFLICT:row={index}")
        seen.add(key)
    return errors

def ingest(bundle_dir: str | Path) -> dict:
    manifest, records = load_bundle(bundle_dir)
    errors = validate_records(records, input_snapshot_id=manifest["input_snapshot_id"])
    return {"input_snapshot_id": manifest["input_snapshot_id"], "record_count": len(records),
            "source_timestamp": manifest.get("source_timestamp"), "validation_status": "PASS" if not errors else "FAIL",
            "errors": errors, "records": records}

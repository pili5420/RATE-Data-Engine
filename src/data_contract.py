from __future__ import annotations

from datetime import datetime, timezone
from typing import Mapping

from .rate_logic import DATA_CONTRACT_VERSION, ENGINE_VERSION, SPEC_VERSION

REQUIRED_METADATA = (
    "spec_version", "data_contract_version", "engine_version",
    "input_snapshot_id", "source_timestamp", "calculation_timestamp",
    "validation_status",
)

def production_envelope(payload: Mapping[str, object], *, input_snapshot_id: str | None,
                        source_timestamp: str | None, validation_status: str) -> dict:
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    return {
        "spec_version": SPEC_VERSION,
        "data_contract_version": DATA_CONTRACT_VERSION,
        "engine_version": ENGINE_VERSION,
        "input_snapshot_id": input_snapshot_id,
        "source_timestamp": source_timestamp,
        "calculation_timestamp": now,
        "validation_status": validation_status,
        "payload": dict(payload),
    }

def validate_envelope(value: Mapping[str, object]) -> list[str]:
    errors = [f"UNDEFINED_FIELD:{key}" for key in REQUIRED_METADATA if key not in value]
    if value.get("spec_version") != SPEC_VERSION:
        errors.append("SCHEMA_SPEC_VERSION")
    if value.get("data_contract_version") != DATA_CONTRACT_VERSION:
        errors.append("SCHEMA_DATA_CONTRACT_VERSION")
    if value.get("engine_version") != ENGINE_VERSION:
        errors.append("SCHEMA_ENGINE_VERSION")
    if value.get("validation_status") not in {"PASS", "FAIL", "BLOCKED"}:
        errors.append("TYPE_VALIDATION:validation_status")
    return errors

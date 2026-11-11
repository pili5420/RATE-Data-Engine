from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Mapping

from .phase_a_state_adapter import load_phase_a_previous_state
from .thin_work_manifest import CONTRACT_VERSION, validate_shadow_manifest

PHASE_A_CONSUMER_CONTRACT = "RATE-THIN-WORK-CONSUMER-PHASE-A-V1"
ALLOWED_PREVIOUS_STATE_REQUIREMENTS = {"REQUIRED", "NOT_REQUIRED_INITIAL_STATE"}
NO_RECALCULATION_TARGETS = (
    "M7",
    "MHE",
    "Stage",
    "Rotation",
    "Smart Money",
    "Top50",
    "Top30",
    "market indicators",
)


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _read_json_file(path: str | Path, error_code: str) -> tuple[dict | None, list[str]]:
    target = Path(path)
    if not target.is_file():
        return None, [error_code]
    try:
        loaded = json.loads(target.read_text(encoding="utf-8"))
    except Exception:
        return None, [error_code.replace("MISSING", "CORRUPTED")]
    if not isinstance(loaded, dict):
        return None, [error_code.replace("MISSING", "CORRUPTED")]
    return loaded, []


def _previous_state_id(previous_state: Mapping[str, object] | None) -> str | None:
    if previous_state is None:
        return None
    for key in ("current_state_id", "state_id"):
        if previous_state.get(key):
            return str(previous_state[key])
    return None


def _previous_state_hash(previous_state: Mapping[str, object] | None) -> str | None:
    if previous_state is None:
        return None
    for key in ("decision_payload_hash", "current_state_hash", "state_hash"):
        if previous_state.get(key):
            return str(previous_state[key])
    return None


def _gate(status: bool, errors: list[str]) -> dict:
    return {"status": "PASS" if status else "FAIL_CLOSED", "errors": errors}


def build_phase_a_consumer_evidence(
    *,
    manifest_path: str | Path,
    previous_state_path: str | Path | None = None,
    previous_state_root: str | Path | None = None,
    previous_trading_date: str | None = None,
    previous_cadence: str | None = None,
    root: str | Path = ".",
    expected_run_id: str | None = None,
    expected_commit_sha: str | None = None,
    expected_production_snapshot_id: str | None = None,
    expected_previous_state_id: str | None = None,
    expected_previous_state_hash: str | None = None,
    now=None,
) -> dict:
    manifest, manifest_errors = _read_json_file(manifest_path, "MISSING_MANIFEST")
    binding_errors = []
    required_expectations = {
        "expected_run_id": expected_run_id,
        "expected_commit_sha": expected_commit_sha,
        "expected_production_snapshot_id": expected_production_snapshot_id,
        "expected_previous_state_id": expected_previous_state_id,
        "expected_previous_state_hash": expected_previous_state_hash,
    }
    for name, value in required_expectations.items():
        if not value:
            binding_errors.append("MISSING_" + name.upper())
    previous_state, previous_errors = load_phase_a_previous_state(
        state_root=previous_state_root or root,
        trading_date=previous_trading_date,
        cadence=previous_cadence,
        expected_previous_state_id=expected_previous_state_id,
        expected_previous_state_hash=expected_previous_state_hash,
        reference_path=previous_state_path,
    )

    manifest_validation = {"validation_status": "FAIL_CLOSED", "errors": manifest_errors}
    if manifest is not None:
        manifest_validation = validate_shadow_manifest(
            manifest,
            root=root,
            expected_run_id=expected_run_id,
            expected_commit_sha=expected_commit_sha,
            expected_production_snapshot_id=expected_production_snapshot_id,
            now=now,
        )

    errors = list(manifest_validation.get("errors", [])) + previous_errors + binding_errors
    previous_requirement = manifest.get("previous_state_requirement") if manifest else None
    previous_id = _previous_state_id(previous_state)
    previous_hash = _previous_state_hash(previous_state)
    if previous_requirement not in ALLOWED_PREVIOUS_STATE_REQUIREMENTS:
        errors.append("INVALID_PREVIOUS_STATE_REQUIREMENT")
    if previous_requirement == "REQUIRED" and not previous_id:
        errors.append("MISSING_PREVIOUS_STATE_ID")
    if previous_requirement == "REQUIRED" and not previous_hash:
        errors.append("MISSING_PREVIOUS_STATE_HASH")
    bound_previous_id = manifest.get("previous_state_id") if isinstance(manifest, dict) else None
    if bound_previous_id is not None and previous_id != bound_previous_id:
        errors.append("PREVIOUS_STATE_ID_MISMATCH")
    if expected_previous_state_id and previous_id != expected_previous_state_id:
        errors.append("PREVIOUS_STATE_ID_MISMATCH")
    if expected_previous_state_hash and previous_hash != expected_previous_state_hash:
        errors.append("PREVIOUS_STATE_HASH_MISMATCH")

    pass_status = not errors
    production_snapshot_id = manifest.get("production_snapshot_id") if manifest else None
    proposed_payload = {
        "contract": PHASE_A_CONSUMER_CONTRACT,
        "production_snapshot_id": production_snapshot_id,
        "previous_state_id": previous_id,
        "previous_state_hash": previous_hash,
        "previous_production_snapshot_id": previous_state.get("previous_production_snapshot_id") if previous_state else None,
        "run_id": manifest.get("run_id") if manifest else None,
        "commit_sha": manifest.get("commit_sha") if manifest else None,
    }
    proposed_current_state_id = "rate-shadow-preview-" + hashlib.sha256(_canonical_bytes(proposed_payload)).hexdigest()[:24] if pass_status else None
    fail_closed_reason = sorted(set(errors))

    evidence = {
        "system": "RATE",
        "consumer_contract": PHASE_A_CONSUMER_CONTRACT,
        "manifest_version": manifest.get("version") if manifest else None,
        "cadence": manifest.get("cadence") if manifest else None,
        "run_id": manifest.get("run_id") if manifest else None,
        "production_snapshot_id": production_snapshot_id,
        "commit_sha": manifest.get("commit_sha") if manifest else None,
        "manifest_validation": manifest_validation,
        "previous_state_id": previous_id,
        "previous_state_hash": previous_hash,
        "previous_production_snapshot_id": previous_state.get("previous_production_snapshot_id") if previous_state else None,
        "proposed_current_state_id": proposed_current_state_id,
        "binding_gate": _gate(not any(error in errors for error in ("CONTRACT_VERSION_MISMATCH", "PRODUCTION_SNAPSHOT_BINDING_MISMATCH", "RUN_ID_MISMATCH", "COMMIT_MISMATCH", "MISSING_PRODUCTION_SNAPSHOT_ID", "MISSING_MANIFEST", "CORRUPTED_MANIFEST", "MISSING_EXPECTED_RUN_ID", "MISSING_EXPECTED_COMMIT_SHA", "MISSING_EXPECTED_PRODUCTION_SNAPSHOT_ID", "MISSING_EXPECTED_PREVIOUS_STATE_ID", "MISSING_EXPECTED_PREVIOUS_STATE_HASH", "PREVIOUS_STATE_HASH_MISMATCH")), fail_closed_reason),
        "freshness_gate": _gate("FRESHNESS_STATUS_NOT_PASS" not in errors and "STALE_ARTIFACT" not in errors and "FUTURE_DATED_ARTIFACT" not in errors, fail_closed_reason),
        "validation_gate": _gate("VALIDATION_STATUS_NOT_PASS" not in errors, fail_closed_reason),
        "source_status_gate": _gate("SOURCE_STATUS_NOT_PASS" not in errors, fail_closed_reason),
        "dataset_gate": _gate("MISSING_REQUIRED_DATASET" not in errors, fail_closed_reason),
        "blocked_dependency_gate": _gate("BLOCKED_DEPENDENCIES_PRESENT" not in errors, fail_closed_reason),
        "previous_state_gate": _gate(not any(error in ("INVALID_PREVIOUS_STATE_REQUIREMENT", "MISSING_PREVIOUS_STATE", "CORRUPTED_PREVIOUS_STATE", "MISSING_PREVIOUS_STATE_ID", "MISSING_PREVIOUS_STATE_HASH", "PREVIOUS_STATE_ID_MISMATCH", "PREVIOUS_STATE_HASH_MISMATCH", "PREVIOUS_STATE_REFERENCE_MISMATCH") or error.startswith("LIVE_") or error.startswith("RECOVERY_") or error.startswith("REBASELINE_") for error in errors), fail_closed_reason),
        "decision_preview_allowed": pass_status,
        "portfolio_preview_allowed": pass_status,
        "ledger_preview_allowed": pass_status,
        "state_mutation_allowed": False,
        "portfolio_mutation_allowed": False,
        "ledger_mutation_allowed": False,
        "production_mutation_allowed": False,
        "fallback_used": False,
        "no_recalculation_evidence": {
            "status": "PASS",
            "not_calculated": list(NO_RECALCULATION_TARGETS),
            "source": "production_manifest_and_bound_payload_references_only",
        },
        "fail_closed_reason": fail_closed_reason,
        "status": "PASS" if pass_status else "FAIL_CLOSED",
    }
    if manifest and manifest.get("version") != CONTRACT_VERSION:
        evidence["fail_closed_reason"].append("RATE_MANIFEST_CONTRACT_MISMATCH")
    return evidence

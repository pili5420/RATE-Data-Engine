from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping

from .source_bundle import REQUIRED_BUNDLE_DOMAINS, SourceBundleError

CONTRACT_VERSION = "RATE-THIN-WORK-PRODUCTION-BUNDLE-MANIFEST-V1"
INTRADAY_BLOCKED_DEPENDENCY = "EXTERNAL_AUTHORIZED_INTRADAY_FEED_DEPENDENCY"
INTRADAY_CADENCES = {"09:30", "12:00", "0930", "1200"}
REQUIRED_PREVIOUS_STATE_REQUIREMENTS = {"REQUIRED", "NOT_REQUIRED_INITIAL_STATE"}
REQUIRED_TOP_LEVEL_FIELDS = {
    "system",
    "version",
    "cadence",
    "run_id",
    "event",
    "production_snapshot_id",
    "commit_sha",
    "generated_at",
    "market_date",
    "snapshot_type",
    "source_status",
    "freshness_status",
    "validation_status",
    "required_datasets",
    "datasets_present",
    "datasets_missing",
    "blocked_dependencies",
    "input_snapshot_id",
    "previous_state_requirement",
    "payload_references",
}


class ThinWorkManifestError(SourceBundleError):
    pass


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ThinWorkManifestError("CORRUPTED_MANIFEST_OR_ARTIFACT") from exc


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _timestamp(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except Exception as exc:
        raise ThinWorkManifestError("INVALID_TIMESTAMP") from exc
    if parsed.tzinfo is None:
        raise ThinWorkManifestError("TIMESTAMP_REQUIRES_TIMEZONE")
    return parsed


def _dataset_status(source_bundle: Mapping[str, object]) -> tuple[list[str], list[str]]:
    required = sorted(REQUIRED_BUNDLE_DOMAINS)
    domains = source_bundle.get("domains")
    if isinstance(domains, list):
        present = sorted({str(item.get("domain")) for item in domains if isinstance(item, dict) and item.get("domain")})
    else:
        present = sorted(str(item.get("domain") or item.get("name")) for item in source_bundle.get("sources", []) if isinstance(item, dict) and (item.get("domain") or item.get("name")))
    missing = sorted(set(required) - set(present))
    for item in source_bundle.get("required_missing", []):
        if str(item) not in missing:
            missing.append(str(item))
    return required, sorted(set(missing))


def build_shadow_manifest(
    *,
    production_artifact_path: str | Path,
    cadence: str,
    run_id: str,
    event: str,
    commit_sha: str,
    market_date: str,
    generated_at: str | None = None,
    previous_state_requirement: str = "REQUIRED",
    snapshot_type: str = "SHADOW_PRODUCTION_BUNDLE",
) -> dict:
    artifact_path = Path(production_artifact_path)
    if not artifact_path.is_file():
        raise ThinWorkManifestError("MISSING_ARTIFACT")
    source_bundle = _read_json(artifact_path)
    required, missing = _dataset_status(source_bundle)
    blocked = list(source_bundle.get("blocked_dependencies", []))
    if cadence in INTRADAY_CADENCES and source_bundle.get("authorized_intraday_feed") != "PASS":
        blocked.append(INTRADAY_BLOCKED_DEPENDENCY)
    validation_status = str(source_bundle.get("validation_status", "BLOCKED"))
    freshness_status = str(source_bundle.get("freshness_status", "BLOCKED"))
    source_status = "PASS" if validation_status == "PASS" and not missing and not blocked else "BLOCKED"
    generated = generated_at or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    manifest = {
        "system": "RATE",
        "version": CONTRACT_VERSION,
        "cadence": cadence,
        "run_id": run_id,
        "event": event,
        "production_snapshot_id": source_bundle.get("production_snapshot_id") or source_bundle.get("snapshot_id"),
        "commit_sha": commit_sha,
        "generated_at": generated,
        "market_date": market_date,
        "snapshot_type": snapshot_type,
        "source_status": source_status,
        "freshness_status": freshness_status,
        "validation_status": validation_status if validation_status in {"PASS", "FAIL"} else "BLOCKED",
        "authorized_intraday_feed_status": source_bundle.get("authorized_intraday_feed"),
        "required_datasets": required,
        "datasets_present": sorted(set(required) - set(missing)),
        "datasets_missing": missing,
        "blocked_dependencies": sorted(set(blocked)),
        "input_snapshot_id": source_bundle.get("input_snapshot_id"),
        "previous_state_requirement": previous_state_requirement,
        "payload_references": [{
            "path": artifact_path.as_posix(),
            "sha256": _sha256(artifact_path),
            "artifact": source_bundle.get("artifact", "RATE_PRODUCTION_SOURCE_BUNDLE"),
        }],
    }
    manifest["manifest_sha256"] = hashlib.sha256(_canonical_bytes({k: v for k, v in manifest.items() if k != "manifest_sha256"})).hexdigest()
    return manifest


def validate_shadow_manifest(
    manifest: Mapping[str, object],
    *,
    root: str | Path = ".",
    expected_run_id: str | None = None,
    expected_commit_sha: str | None = None,
    expected_production_snapshot_id: str | None = None,
    now: datetime | None = None,
) -> dict:
    errors: list[str] = []
    root_path = Path(root)
    now = now or datetime.now(timezone.utc)
    missing_fields = sorted(REQUIRED_TOP_LEVEL_FIELDS - set(manifest))
    errors.extend(f"MISSING_FIELD:{field}" for field in missing_fields)
    if manifest.get("version") != CONTRACT_VERSION:
        errors.append("CONTRACT_VERSION_MISMATCH")
    if expected_run_id is not None and manifest.get("run_id") != expected_run_id:
        errors.append("RUN_ID_MISMATCH")
    if expected_commit_sha is not None and manifest.get("commit_sha") != expected_commit_sha:
        errors.append("COMMIT_MISMATCH")
    if expected_production_snapshot_id is not None and manifest.get("production_snapshot_id") != expected_production_snapshot_id:
        errors.append("PRODUCTION_SNAPSHOT_BINDING_MISMATCH")
    if not manifest.get("production_snapshot_id"):
        errors.append("MISSING_PRODUCTION_SNAPSHOT_ID")
    if manifest.get("previous_state_requirement") not in REQUIRED_PREVIOUS_STATE_REQUIREMENTS:
        errors.append("INVALID_PREVIOUS_STATE_REQUIREMENT")
    try:
        generated_at = _timestamp(str(manifest.get("generated_at", "")))
        if generated_at > now:
            errors.append("FUTURE_DATED_ARTIFACT")
        if (now - generated_at).total_seconds() > 36 * 60 * 60:
            errors.append("STALE_ARTIFACT")
    except ThinWorkManifestError as exc:
        errors.append(str(exc))
    if manifest.get("validation_status") == "FAIL":
        errors.append("VALIDATION_FAIL")
    if manifest.get("blocked_dependencies"):
        errors.append("BLOCKED_DEPENDENCIES_PRESENT")
    if manifest.get("datasets_missing"):
        errors.append("MISSING_REQUIRED_DATASET")
    if (
        manifest.get("cadence") in INTRADAY_CADENCES
        and manifest.get("authorized_intraday_feed_status") != "PASS"
        and INTRADAY_BLOCKED_DEPENDENCY not in set(manifest.get("blocked_dependencies", []))
    ):
        errors.append("MISSING_INTRADAY_BLOCKED_DEPENDENCY")
    for reference in manifest.get("payload_references", []):
        path = root_path / str(reference.get("path", ""))
        if not path.is_file():
            errors.append(f"MISSING_ARTIFACT:{reference.get('path')}")
            continue
        if reference.get("sha256") != _sha256(path):
            errors.append(f"PAYLOAD_REFERENCE_HASH_MISMATCH:{reference.get('path')}")
    expected_hash = manifest.get("manifest_sha256")
    actual_hash = hashlib.sha256(_canonical_bytes({k: v for k, v in manifest.items() if k != "manifest_sha256"})).hexdigest()
    if expected_hash != actual_hash:
        errors.append("CORRUPTED_MANIFEST")
    status = "PASS" if not errors else "FAIL_CLOSED"
    return {"validation_status": status, "errors": errors, "state_mutation_allowed": False, "portfolio_mutation_allowed": False, "ledger_mutation_allowed": False}

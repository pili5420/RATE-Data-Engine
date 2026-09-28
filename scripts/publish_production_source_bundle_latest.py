
from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

LATEST_RELATIVE = Path("artifacts/RATE_PRODUCTION_SOURCE_BUNDLE_LATEST.json")
SNAPSHOT_ROOT_RELATIVE = Path("artifacts/production_source_snapshots")
REQUIRED_LATEST_FIELDS = ("snapshot_id", "trading_date", "cadence", "retrieval_timestamp", "workflow_run_id", "previous_snapshot_id", "validation_status")
CADENCE_FRESHNESS_MINUTES = {"07:30": 180, "09:30": 45, "12:00": 90, "19:30": 180}
REQUIRED_DECISION_RECORD_COUNT = 30


def canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def atomic_write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    finally:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass


def load_json(path: str | Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

def parse_utc(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except Exception:
        return None


def validate_freshness(bundle: Mapping[str, Any], *, trading_date: str, cadence: str, now: datetime | None = None) -> dict:
    source_provenance = bundle.get("source_provenance") or {}
    retrieval_timestamp = source_provenance.get("retrieval_timestamp") or bundle.get("retrieval_timestamp")
    parsed = parse_utc(retrieval_timestamp) if retrieval_timestamp else None
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    source_trading_date = bundle.get("trading_date") or source_provenance.get("trading_date")
    age_minutes = None if parsed is None else (now - parsed).total_seconds() / 60
    max_age = CADENCE_FRESHNESS_MINUTES.get(cadence)
    checks = {
        "retrieval_timestamp_parseable": parsed is not None,
        "not_future_dated": parsed is not None and parsed <= now,
        "source_trading_date_matches": source_trading_date in (None, trading_date),
        "cadence_freshness_window": parsed is not None and max_age is not None and 0 <= age_minutes <= max_age,
        "stale_previous_day_rejected": source_trading_date in (None, trading_date),
    }
    return {
        "status": "PASS" if all(checks.values()) else "FAIL",
        "checks": checks,
        "retrieval_timestamp": retrieval_timestamp,
        "source_trading_date": source_trading_date,
        "age_minutes": age_minutes,
        "max_age_minutes": max_age,
    }


def validate_production_source_bundle(bundle: Mapping[str, Any], *, trading_date: str, cadence: str) -> dict:
    source_provenance = bundle.get("source_provenance") or {}
    retrieval_timestamp = source_provenance.get("retrieval_timestamp") or bundle.get("retrieval_timestamp")
    records = bundle.get("decision_records") if "decision_records" in bundle else (bundle.get("records") or [])
    freshness = validate_freshness(bundle, trading_date=trading_date, cadence=cadence)
    coverage = bundle.get("coverage") or (bundle.get("decision_record_coverage") or {}).get("coverage")
    record_count = len(records) if isinstance(records, list) else 0
    calendar_gate = bundle.get("trading_calendar_gate") or {}
    holiday_snapshot = bundle.get("holiday_snapshot") is True or bundle.get("snapshot_type") == "HOLIDAY"
    holiday_checks = {
        "validation_status": bundle.get("validation_status") == "PASS",
        "source_bundle_validation": bundle.get("source_bundle_validation", "PASS") == "PASS",
        "official_source": source_provenance.get("source") in ("AUTHORIZED_LIVE", "RATE_OFFICIAL_TW_MARKET_DATA_SSOT"),
        "schema_version": bool(bundle.get("schema_version") or bundle.get("bundle_version")),
        "freshness": freshness["status"] == "PASS",
        "provenance": isinstance(source_provenance, dict) and bool(source_provenance),
        "trading_date": bool(trading_date) and freshness["checks"]["source_trading_date_matches"],
        "cadence": cadence in {"07:30", "09:30", "12:00", "19:30"},
        "input_snapshot_id": bool(bundle.get("input_snapshot_id")),
        "holiday_snapshot": holiday_snapshot,
        "calendar_gate": calendar_gate.get("status") == "PASS" and calendar_gate.get("is_trading_day") is False,
    }
    checks = {
        "validation_status": bundle.get("validation_status") == "PASS",
        "source_bundle_validation": bundle.get("source_bundle_validation", "PASS") == "PASS",
        "official_source": source_provenance.get("source") in ("AUTHORIZED_LIVE", "RATE_OFFICIAL_TW_MARKET_DATA_SSOT"),
        "schema_version": bool(bundle.get("schema_version") or bundle.get("bundle_version")),
        "freshness": freshness["status"] == "PASS",
        "provenance": isinstance(source_provenance, dict) and bool(source_provenance),
        "completeness": isinstance(records, list) and record_count == REQUIRED_DECISION_RECORD_COUNT and coverage in (None, f"{REQUIRED_DECISION_RECORD_COUNT}/{REQUIRED_DECISION_RECORD_COUNT}"),
        "trading_date": bool(trading_date) and freshness["checks"]["source_trading_date_matches"],
        "cadence": cadence in {"07:30", "09:30", "12:00", "19:30"},
        "input_snapshot_id": bool(bundle.get("input_snapshot_id")),
    }
    active_checks = holiday_checks if holiday_snapshot else checks
    status = "PASS" if all(active_checks.values()) else "FAIL"
    return {"validation_status": status, "checks": active_checks, "freshness": freshness, "retrieval_timestamp": retrieval_timestamp, "record_count": record_count, "required_record_count": 0 if holiday_snapshot else REQUIRED_DECISION_RECORD_COUNT, "coverage": coverage, "snapshot_type": "HOLIDAY" if holiday_snapshot else "TRADING_DAY"}


def latest_snapshot_id(latest_path: Path) -> str | None:
    if not latest_path.exists():
        return None
    try:
        latest = load_json(latest_path)
    except Exception:
        return None
    if latest.get("validation_status") != "PASS":
        return None
    return latest.get("snapshot_id")


def build_snapshot(bundle: Mapping[str, Any], *, trading_date: str, cadence: str, workflow_run_id: str, workflow_job_id: str | None, previous_snapshot_id: str | None, retrieval_timestamp: str) -> dict:
    bundle_hash = sha256(bundle)
    seed = {"bundle_hash": bundle_hash, "trading_date": trading_date, "cadence": cadence, "workflow_run_id": workflow_run_id, "retrieval_timestamp": retrieval_timestamp}
    snapshot_id = "rate-source-snapshot-" + sha256(seed)[:24]
    return {
        "artifact": "RATE_PRODUCTION_SOURCE_BUNDLE_SNAPSHOT",
        "snapshot_id": snapshot_id,
        "trading_date": trading_date,
        "cadence": cadence,
        "retrieval_timestamp": retrieval_timestamp,
        "workflow_run_id": workflow_run_id,
        "workflow_job_id": workflow_job_id,
        "previous_snapshot_id": previous_snapshot_id,
        "validation_status": "PASS",
        "input_snapshot_id": bundle.get("input_snapshot_id"),
        "snapshot_type": "HOLIDAY" if bundle.get("holiday_snapshot") is True or bundle.get("snapshot_type") == "HOLIDAY" else "TRADING_DAY",
        "source_bundle_hash": bundle_hash,
        "immutable": True,
        "bundle": bundle,
    }


def publish_latest(*, source_bundle_path: str | Path, trading_date: str, cadence: str, artifacts_root: str | Path = "artifacts", workflow_run_id: str | None = None, workflow_job_id: str | None = None, evidence_output: str | Path | None = None) -> dict:
    root = Path(artifacts_root)
    latest_path = root / "RATE_PRODUCTION_SOURCE_BUNDLE_LATEST.json"
    snapshot_root = root / "production_source_snapshots"
    workflow_run_id = workflow_run_id or os.getenv("GITHUB_RUN_ID") or "local"
    workflow_job_id = workflow_job_id or os.getenv("ACTIONS_JOB_ID") or os.getenv("GITHUB_JOB")
    bundle = load_json(source_bundle_path)
    validation = validate_production_source_bundle(bundle, trading_date=trading_date, cadence=cadence)
    previous_snapshot_id = latest_snapshot_id(latest_path)
    evidence = {
        "artifact": "RATE_PRODUCTION_SOURCE_BUNDLE_LATEST_UPDATE_EVIDENCE",
        "trading_date": trading_date,
        "cadence": cadence,
        "workflow_run_id": workflow_run_id,
        "workflow_job_id": workflow_job_id,
        "previous_snapshot_id": previous_snapshot_id,
        "source_bundle_path": str(source_bundle_path),
        "validation": validation,
        "latest_updated": False,
        "publish_result": "BLOCKED",
    }
    if validation["validation_status"] != "PASS":
        evidence["blocking_reason"] = "SOURCE_BUNDLE_VALIDATION_NOT_PASS"
        if evidence_output:
            atomic_write_json(Path(evidence_output), evidence)
        return evidence
    retrieval_timestamp = validation["retrieval_timestamp"] or utc_now()
    snapshot = build_snapshot(bundle, trading_date=trading_date, cadence=cadence, workflow_run_id=workflow_run_id, workflow_job_id=workflow_job_id, previous_snapshot_id=previous_snapshot_id, retrieval_timestamp=retrieval_timestamp)
    snapshot_dir = snapshot_root / trading_date / cadence.replace(":", "")
    snapshot_path = snapshot_dir / f"{snapshot['snapshot_id']}.json"
    latest = {k: snapshot[k] for k in REQUIRED_LATEST_FIELDS}
    latest.update({
        "artifact": "RATE_PRODUCTION_SOURCE_BUNDLE_LATEST",
        "workflow_job_id": workflow_job_id,
        "input_snapshot_id": snapshot.get("input_snapshot_id"),
        "snapshot_type": snapshot.get("snapshot_type"),
        "source_bundle_hash": snapshot["source_bundle_hash"],
        "immutable_snapshot_path": str(snapshot_path).replace("\\", "/"),
        "schema_version": "RATE-PRODUCTION-SOURCE-LATEST-V1",
    })
    atomic_write_json(snapshot_path, snapshot)
    atomic_write_json(latest_path, latest)
    evidence.update({
        "validation_status": "PASS",
        "snapshot_id": snapshot["snapshot_id"],
        "current_snapshot_id": snapshot["snapshot_id"],
        "current_snapshot_hash": snapshot["source_bundle_hash"],
        "immutable_snapshot_path": latest["immutable_snapshot_path"],
        "latest_path": str(latest_path).replace("\\", "/"),
        "latest_updated": True,
        "publish_result": "PASS",
    })
    if evidence_output:
        atomic_write_json(Path(evidence_output), evidence)
    return evidence


def main() -> int:
    parser = argparse.ArgumentParser(description="Publish immutable RATE production source bundle snapshot and atomically update LATEST after PASS validation.")
    parser.add_argument("--source-bundle", required=True)
    parser.add_argument("--trading-date", required=True)
    parser.add_argument("--cadence", required=True, choices=["07:30", "09:30", "12:00", "19:30"])
    parser.add_argument("--artifacts-root", default="artifacts")
    parser.add_argument("--workflow-run-id", default=os.getenv("GITHUB_RUN_ID"))
    parser.add_argument("--workflow-job-id", default=os.getenv("ACTIONS_JOB_ID") or os.getenv("GITHUB_JOB"))
    parser.add_argument("--evidence-output", default="artifacts/RATE_PRODUCTION_SOURCE_BUNDLE_LATEST_UPDATE_EVIDENCE.json")
    args = parser.parse_args()
    evidence = publish_latest(source_bundle_path=args.source_bundle, trading_date=args.trading_date, cadence=args.cadence, artifacts_root=args.artifacts_root, workflow_run_id=args.workflow_run_id, workflow_job_id=args.workflow_job_id, evidence_output=args.evidence_output)
    print(json.dumps(evidence, ensure_ascii=False, sort_keys=True))
    return 0 if evidence.get("publish_result") == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.cer074_acceptance import atomic_write_json
from src.production_live_state import (CADENCE_DIR, MANIFEST_NAME, PERSIST_NAME, STATE_NAME,
                                       file_hash, read_object, require, validate_recovery_source_material)

AUTHORIZATION_NAME = "RATE_PRODUCTION_RECOVERY_AUTHORIZATION_MANIFEST.json"
CONSUMPTION_NAME = "RATE_PRODUCTION_RECOVERY_AUTHORIZATION_CONSUMPTION_EVIDENCE.json"
FORBIDDEN_SOURCE_PARTS = {"fixture", "fixtures", "staging", "cache", "synthetic"}
AUTHORIZATION_ROOT = Path("control") / "recovery_authorizations"


def _canonical_hash(payload):
    clone = dict(payload)
    clone.pop("manifest_integrity_hash", None)
    clone.pop("authorization_blob_sha256", None)
    clone.pop("approval_commit_sha", None)
    blob = json.dumps(clone, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def _safe_authorization_id(value):
    require(isinstance(value, str) and value.startswith("CC-"), "RECOVERY_BOOTSTRAP_AUTHORIZATION_REQUIRED")
    require(all(c.isalnum() or c in "-_." for c in value), "RECOVERY_BOOTSTRAP_AUTHORIZATION_REQUIRED")
    return value


def _forbid_fallback_path(path, reason):
    require(not (FORBIDDEN_SOURCE_PARTS & {part.lower() for part in Path(path).parts}), reason)


def _git(repository_root, *args):
    result = subprocess.run(["git", "-C", str(repository_root), *args], capture_output=True, text=True)
    require(result.returncode == 0, result.stderr.strip() or "RECOVERY_AUTHORIZATION_GIT_VALIDATION_FAILED")
    return result.stdout.strip()


def _authorization_path(repository_root, authorization_id):
    relative = AUTHORIZATION_ROOT / authorization_id / AUTHORIZATION_NAME
    path = Path(repository_root) / relative
    require(path.resolve().is_relative_to((Path(repository_root) / AUTHORIZATION_ROOT).resolve()),
            "RECOVERY_AUTHORIZATION_PATH_INVALID")
    return relative, path


def _validate_approval_commit(repository_root, relative_path, authorization, current_main_sha):
    approval = authorization.get("approval_commit_sha")
    require(isinstance(approval, str) and len(approval) == 40
            and all(c in "0123456789abcdef" for c in approval),
            "RECOVERY_APPROVAL_COMMIT_INVALID")
    approval_check = subprocess.run(["git", "-C", str(repository_root), "cat-file", "-e", f"{approval}^{{commit}}"],
                                    capture_output=True, text=True)
    require(approval_check.returncode == 0, "RECOVERY_APPROVAL_COMMIT_INVALID")
    current_check = subprocess.run(["git", "-C", str(repository_root), "cat-file", "-e", f"{current_main_sha}^{{commit}}"],
                                   capture_output=True, text=True)
    require(current_check.returncode == 0, "RECOVERY_APPROVAL_COMMIT_INVALID")
    result = subprocess.run(["git", "-C", str(repository_root), "merge-base", "--is-ancestor", approval, current_main_sha],
                            capture_output=True, text=True)
    require(result.returncode == 0, "RECOVERY_APPROVAL_COMMIT_NOT_MAIN_ANCESTOR")
    committed = json.loads(_git(repository_root, "show", f"{approval}:{relative_path.as_posix()}"))
    current = authorization
    require(_canonical_hash(committed) == _canonical_hash(current),
            "RECOVERY_AUTHORIZATION_BYTES_CHANGED_AFTER_APPROVAL")
    require(_canonical_hash(authorization) == authorization.get("authorization_blob_sha256"),
            "RECOVERY_AUTHORIZATION_BLOB_HASH_MISMATCH")


def bootstrap_recovery_state(*, source_persist_path, source_state_path, trading_date, cadence,
                             recovery_authorization_id, artifacts_root="artifacts",
                             workflow_run_id=None, workflow_job_id=None, event_name=None,
                             commit_sha=None, ref=None, evidence_output=None,
                             recovery_source_type="FORMAL_ACCEPTED_RECOVERY_SOURCE",
                             repository_root="."):
    out = {"artifact": "RATE_PRODUCTION_RECOVERY_BOOTSTRAP_EVIDENCE", "validation_status": "BLOCKED",
           "trading_date": trading_date, "cadence": cadence, "recovery_mode": True,
           "scheduled_soak_credit": False, "acceptance_counter_reset": False,
           "workflow_run_id": workflow_run_id, "workflow_job_id": workflow_job_id,
           "recovery_authorization_id": recovery_authorization_id}
    try:
        event_name = event_name or os.getenv("GITHUB_EVENT_NAME")
        commit_sha = commit_sha or os.getenv("GITHUB_SHA")
        ref = ref or os.getenv("GITHUB_REF")
        require(event_name == "workflow_dispatch" and ref == "refs/heads/main",
                "RECOVERY_BOOTSTRAP_AUTHORIZATION_REQUIRED")
        require(str(workflow_run_id or "").isdigit() and str(workflow_job_id or "").isdigit()
                and isinstance(commit_sha, str) and len(commit_sha) == 40
                and all(c in "0123456789abcdef" for c in commit_sha),
                "RECOVERY_BOOTSTRAP_AUTHORIZATION_REQUIRED")
        authorization_id = _safe_authorization_id(recovery_authorization_id)
        repository_root = Path(repository_root).resolve()
        relative_authorization_path, authorization_manifest_path = _authorization_path(repository_root, authorization_id)
        require(authorization_manifest_path.is_file(), "RECOVERY_AUTHORIZATION_MANIFEST_REQUIRED")
        authorization = read_object(authorization_manifest_path)
        require(authorization.get("artifact") == "RATE_PRODUCTION_RECOVERY_AUTHORIZATION_MANIFEST",
                "RECOVERY_AUTHORIZATION_MANIFEST_INVALID")
        require(authorization.get("manifest_integrity_hash") == _canonical_hash(authorization),
                "RECOVERY_AUTHORIZATION_MANIFEST_TAMPERED")
        _validate_approval_commit(repository_root, relative_authorization_path, authorization, commit_sha)
        require(authorization.get("authorization_id") == authorization_id,
                "RECOVERY_AUTHORIZATION_ID_MISMATCH")
        require(authorization.get("defect_id") == "RATE-SOAK-005",
                "RECOVERY_AUTHORIZATION_DEFECT_MISMATCH")
        require(authorization.get("authorization_status") == "APPROVED",
                "RECOVERY_AUTHORIZATION_NOT_APPROVED")
        require(authorization.get("approved_by") == "CONTROL_CENTER",
                "RECOVERY_AUTHORIZATION_APPROVER_INVALID")
        require(authorization.get("approved_source_type") == recovery_source_type == "FORMAL_ACCEPTED_RECOVERY_SOURCE",
                "RECOVERY_SOURCE_NOT_FORMALLY_ACCEPTED")
        require(authorization.get("scheduled_soak_credit") is False
                and authorization.get("acceptance_counter_reset") is False
                and authorization.get("single_use") is True,
                "RECOVERY_AUTHORIZATION_POLICY_INVALID")
        require(authorization.get("approved_target_trading_date") == trading_date
                and authorization.get("approved_target_cadence") == cadence,
                "RECOVERY_AUTHORIZATION_TARGET_MISMATCH")
        require(authorization.get("approved_trading_date") == trading_date
                and authorization.get("approved_cadence") == cadence,
                "RECOVERY_AUTHORIZATION_SOURCE_SLOT_MISMATCH")
        for source_path in (Path(source_persist_path), Path(source_state_path)):
            _forbid_fallback_path(source_path, "RECOVERY_SOURCE_FALLBACK_FORBIDDEN")
        source_persist = read_object(source_persist_path)
        source_state = read_object(source_state_path)
        require(file_hash(source_persist_path) == authorization.get("approved_source_persist_sha256"),
                "RECOVERY_SOURCE_PERSIST_HASH_MISMATCH")
        require(file_hash(source_state_path) == authorization.get("approved_source_state_sha256"),
                "RECOVERY_SOURCE_STATE_FILE_HASH_MISMATCH")
        state, legacy_compatibility = validate_recovery_source_material(source_persist, source_state, trading_date, cadence)
        require(state["current_state_id"] == authorization.get("approved_source_state_id"),
                "RECOVERY_SOURCE_STATE_ID_MISMATCH")
        require(state["decision_payload_hash"] == authorization.get("approved_source_state_hash"),
                "RECOVERY_SOURCE_STATE_HASH_MISMATCH")
        root = Path(artifacts_root)
        directory = root / "production_state" / "live" / trading_date / CADENCE_DIR[cadence]
        require(directory.resolve().is_relative_to((root / "production_state").resolve()), "LIVE_STATE_PATH_ESCAPE")
        consumption_dir = root / "production_state" / "recovery_authorizations" / authorization_id
        consumption_path = consumption_dir / CONSUMPTION_NAME
        require(not consumption_path.exists(), "RECOVERY_AUTHORIZATION_ALREADY_CONSUMED")
        for name in (PERSIST_NAME, STATE_NAME, MANIFEST_NAME):
            require(not (directory / name).exists(), "LIVE_STATE_CANONICAL_SLOT_EXISTS")
        atomic_write_json(directory / STATE_NAME, source_state)
        atomic_write_json(directory / PERSIST_NAME, source_persist)
        manifest = {"artifact": "RATE_PRODUCTION_STATE_MANIFEST", "validation_status": "PASS",
                    "trading_date": trading_date, "cadence": cadence,
                    "event_name": event_name, "ref": ref, "commit_sha": commit_sha,
                    "workflow_run_id": workflow_run_id, "workflow_job_id": workflow_job_id,
                    "recovery_mode": True, "scheduled_soak_credit": False,
                    "acceptance_counter_reset": False,
                    "recovery_authorization_id": authorization_id,
                    "recovery_authorization_manifest_hash": authorization["manifest_integrity_hash"],
                    "recovery_authorization_blob_sha256": authorization["authorization_blob_sha256"],
                    "approval_commit_sha": authorization["approval_commit_sha"],
                    "source_state_id": state["current_state_id"],
                    "source_state_hash": state["decision_payload_hash"],
                    "legacy_recovery_schema_compatibility": legacy_compatibility,
                    "current_state_id": state["current_state_id"],
                    "current_state_hash": state["decision_payload_hash"],
                    "files": {name: file_hash(directory / name) for name in (PERSIST_NAME, STATE_NAME)}}
        atomic_write_json(directory / MANIFEST_NAME, manifest)
        latest_path = root / "RATE_PRODUCTION_STATE_LATEST.json"
        latest = read_object(latest_path) if latest_path.exists() else None
        if not latest or (latest.get("trading_date", ""), latest.get("cadence", "")) <= (trading_date, cadence):
            atomic_write_json(latest_path, {"artifact": "RATE_PRODUCTION_STATE_LATEST",
                "validation_status": "PASS", "trading_date": trading_date, "cadence": cadence,
                "workflow_run_id": workflow_run_id, "workflow_job_id": workflow_job_id,
                "current_state_id": state["current_state_id"],
                "current_state_hash": state["decision_payload_hash"],
                "previous_state_id": state["previous_state_id"],
                "live_state_evidence_path": (directory / PERSIST_NAME).as_posix(),
                "recovery_mode": True, "scheduled_soak_credit": False,
                "acceptance_counter_reset": False,
                "recovery_authorization_id": authorization_id})
        consumption = {"artifact": "RATE_PRODUCTION_RECOVERY_AUTHORIZATION_CONSUMPTION_EVIDENCE",
                       "validation_status": "PASS", "authorization_id": authorization_id,
                       "consumed": True,
                       "consumed_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                       "workflow_run_id": workflow_run_id, "workflow_job_id": workflow_job_id,
                       "commit_sha": commit_sha, "source_state_id": state["current_state_id"],
                       "source_state_hash": state["decision_payload_hash"],
                       "target_trading_date": trading_date, "target_cadence": cadence,
                       "recovery_manifest_hash": authorization["manifest_integrity_hash"],
                       "authorization_blob_sha256": authorization["authorization_blob_sha256"],
                       "approval_commit_sha": authorization["approval_commit_sha"],
                       "scheduled_soak_credit": False, "acceptance_counter_reset": False}
        atomic_write_json(consumption_path, consumption)
        out.update(validation_status="PASS", live_state_updated=True,
                   destination_live_state_path=(directory / PERSIST_NAME).as_posix(),
                   authorization_consumption_path=consumption_path.as_posix(),
                   source_state_id=state["current_state_id"],
                   source_state_hash=state["decision_payload_hash"],
                   recovery_source_type=recovery_source_type,
                   legacy_recovery_schema_compatibility=legacy_compatibility,
                   previous_state_id=state["previous_state_id"])
    except (RuntimeError, OSError, ValueError, KeyError, TypeError) as exc:
        out["blocking_reason"] = str(exc)
    if evidence_output:
        atomic_write_json(Path(evidence_output), out)
    return out


def main():
    parser = argparse.ArgumentParser(description="Authorized one-time RATE production recovery bootstrap.")
    parser.add_argument("--source-persist", required=True)
    parser.add_argument("--source-state", required=True)
    parser.add_argument("--trading-date", required=True)
    parser.add_argument("--cadence", required=True, choices=sorted(CADENCE_DIR))
    parser.add_argument("--recovery-authorization-id", required=True)
    parser.add_argument("--recovery-source-type", required=True, choices=["FORMAL_ACCEPTED_RECOVERY_SOURCE"])
    parser.add_argument("--repository-root", default=".")
    parser.add_argument("--artifacts-root", default="artifacts")
    parser.add_argument("--workflow-run-id")
    parser.add_argument("--workflow-job-id")
    parser.add_argument("--evidence-output", default="artifacts/production_state/RATE_PRODUCTION_RECOVERY_BOOTSTRAP_EVIDENCE.json")
    args = parser.parse_args()
    out = bootstrap_recovery_state(source_persist_path=args.source_persist, source_state_path=args.source_state,
                                   trading_date=args.trading_date, cadence=args.cadence,
                                   recovery_authorization_id=args.recovery_authorization_id,
                                   recovery_source_type=args.recovery_source_type,
                                   repository_root=args.repository_root,
                                   artifacts_root=args.artifacts_root,
                                   workflow_run_id=args.workflow_run_id,
                                   workflow_job_id=args.workflow_job_id,
                                   evidence_output=args.evidence_output)
    print(json.dumps(out, ensure_ascii=False, sort_keys=True))
    return 0 if out["validation_status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())

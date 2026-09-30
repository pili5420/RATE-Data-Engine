from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.cer074_acceptance import atomic_write_json
from src.production_live_state import CADENCE_DIR, MANIFEST_NAME, PERSIST_NAME, STATE_NAME, file_hash, read_object, require, validate_material


def bootstrap_recovery_state(*, source_persist_path, source_state_path, trading_date, cadence,
                             recovery_authorization_id, artifacts_root="artifacts",
                             workflow_run_id=None, workflow_job_id=None, event_name=None,
                             commit_sha=None, ref=None, evidence_output=None,
                             recovery_source_type="FORMAL_ACCEPTED_RECOVERY_SOURCE"):
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
        require(isinstance(recovery_authorization_id, str) and recovery_authorization_id.startswith("CC-"),
                "RECOVERY_BOOTSTRAP_AUTHORIZATION_REQUIRED")
        require(recovery_source_type == "FORMAL_ACCEPTED_RECOVERY_SOURCE", "RECOVERY_SOURCE_NOT_FORMALLY_ACCEPTED")
        forbidden_parts = {"fixture", "fixtures", "staging", "cache", "synthetic"}
        for source_path in (Path(source_persist_path), Path(source_state_path)):
            require(not (forbidden_parts & {part.lower() for part in source_path.parts}),
                    "RECOVERY_SOURCE_FALLBACK_FORBIDDEN")
        source_persist = read_object(source_persist_path)
        source_state = read_object(source_state_path)
        state = validate_material(source_persist, source_state, trading_date, cadence)
        root = Path(artifacts_root)
        directory = root / "production_state" / "live" / trading_date / CADENCE_DIR[cadence]
        require(directory.resolve().is_relative_to((root / "production_state").resolve()), "LIVE_STATE_PATH_ESCAPE")
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
                    "recovery_authorization_id": recovery_authorization_id,
                    "source_state_id": state["current_state_id"],
                    "source_state_hash": state["decision_payload_hash"],
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
                "recovery_authorization_id": recovery_authorization_id})
        out.update(validation_status="PASS", live_state_updated=True,
                   destination_live_state_path=(directory / PERSIST_NAME).as_posix(),
                   source_state_id=state["current_state_id"],
                   source_state_hash=state["decision_payload_hash"],
                   recovery_source_type=recovery_source_type,
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
    parser.add_argument("--artifacts-root", default="artifacts")
    parser.add_argument("--workflow-run-id")
    parser.add_argument("--workflow-job-id")
    parser.add_argument("--evidence-output", default="artifacts/production_state/RATE_PRODUCTION_RECOVERY_BOOTSTRAP_EVIDENCE.json")
    args = parser.parse_args()
    out = bootstrap_recovery_state(source_persist_path=args.source_persist, source_state_path=args.source_state,
                                   trading_date=args.trading_date, cadence=args.cadence,
                                   recovery_authorization_id=args.recovery_authorization_id,
                                   recovery_source_type=args.recovery_source_type,
                                   artifacts_root=args.artifacts_root,
                                   workflow_run_id=args.workflow_run_id,
                                   workflow_job_id=args.workflow_job_id,
                                   evidence_output=args.evidence_output)
    print(json.dumps(out, ensure_ascii=False, sort_keys=True))
    return 0 if out["validation_status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())

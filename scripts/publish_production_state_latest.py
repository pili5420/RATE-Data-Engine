from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.cer074_acceptance import atomic_write_json
from src.production_live_state import (ARTIFACTS, CADENCE_DIR, MANIFEST_NAME, PERSIST_NAME, STATE_NAME,
    file_hash, load_live_state, read_object, require, validate_material)
from scripts.resolve_production_runtime_context import CADENCE_PREDECESSOR, _previous_legal_trading_day

REQUIRED = ARTIFACTS


def publish_state(*, persist_evidence_path, trading_date, cadence, artifacts_root="artifacts",
                  workflow_run_id=None, workflow_job_id=None, evidence_output=None,
                  state_root=None, event_name=None, commit_sha=None, ref=None):
    out = {"artifact": "RATE_PRODUCTION_STATE_LIVE_UPDATE_EVIDENCE", "validation_status": "BLOCKED",
           "workflow_run_id": workflow_run_id, "workflow_job_id": workflow_job_id,
           "trading_date": trading_date, "cadence": cadence, "checks": {}, "live_state_updated": False}
    try:
        event_name = event_name or os.getenv("GITHUB_EVENT_NAME")
        commit_sha = commit_sha or os.getenv("GITHUB_SHA")
        ref = ref or os.getenv("GITHUB_REF")
        require(event_name == "schedule" and ref == "refs/heads/main", "LIVE_STATE_SCHEDULE_PROVENANCE_REQUIRED")
        require(str(workflow_run_id or "").isdigit() and str(workflow_job_id or "").isdigit()
                and isinstance(commit_sha, str) and len(commit_sha) == 40
                and all(c in "0123456789abcdef" for c in commit_sha), "LIVE_STATE_SCHEDULE_PROVENANCE_REQUIRED")
        require(state_root is not None, "LIVE_STATE_FULL_DECISION_MISSING")
        payload = read_object(persist_evidence_path)
        state_id = payload.get("current_state_id", "")
        require(isinstance(state_id, str) and state_id.startswith("rate-state-")
                and len(state_id) == 35 and all(c in "0123456789abcdef" for c in state_id[11:]), "LIVE_STATE_ID_INVALID")
        source_root = Path(state_root).resolve()
        source_path = source_root / "decision_state" / CADENCE_DIR[cadence] / (state_id + ".json")
        require(source_path.resolve().is_relative_to(source_root), "LIVE_STATE_PATH_ESCAPE")
        material = read_object(source_path)
        state = validate_material(payload, material, trading_date, cadence)
        root = Path(artifacts_root)
        previous_date = _previous_legal_trading_day(trading_date) if cadence == "07:30" else trading_date
        previous = load_live_state(root / "production_state", previous_date, CADENCE_PREDECESSOR[cadence])
        require(state["previous_state_id"] == previous["state"]["current_state_id"]
                and state["decision"].get("previous_state_hash") == previous["state"]["decision_payload_hash"], "LIVE_STATE_LINEAGE_INVALID")
        # The decision engine owns account changes; transport must preserve the entire transaction prefix.
        old_ledger = previous["state"]["decision"]["transaction_ledger"]["transactions"]
        new_ledger = state["decision"]["transaction_ledger"]["transactions"]
        require(new_ledger[:len(old_ledger)] == old_ledger, "LIVE_STATE_LEDGER_HISTORY_LOST")
        directory = root / "production_state" / "live" / trading_date / CADENCE_DIR[cadence]
        require(directory.resolve().is_relative_to((root / "production_state").resolve()), "LIVE_STATE_PATH_ESCAPE")
        # An existing slot is immutable, including a partial publication. Never overwrite a fork.
        for name, expected in ((PERSIST_NAME, payload), (STATE_NAME, material)):
            path = directory / name
            if path.exists():
                require(read_object(path) == expected, "LIVE_STATE_IMMUTABLE_CONFLICT")
        manifest_path = directory / MANIFEST_NAME
        already_complete = manifest_path.exists()
        if already_complete:
            load_live_state(root / "production_state", trading_date, cadence)
        else:
            atomic_write_json(directory / STATE_NAME, material)
            atomic_write_json(directory / PERSIST_NAME, payload)
            manifest = {"artifact": "RATE_PRODUCTION_STATE_MANIFEST", "validation_status": "PASS",
                        "trading_date": trading_date, "cadence": cadence, "event_name": event_name,
                        "ref": ref, "commit_sha": commit_sha, "workflow_run_id": workflow_run_id,
                        "workflow_job_id": workflow_job_id, "current_state_id": state_id,
                        "current_state_hash": state["decision_payload_hash"],
                        "files": {name: file_hash(directory / name) for name in (PERSIST_NAME, STATE_NAME)}}
            # Written last: interrupted publication cannot resolve as a usable live state.
            atomic_write_json(manifest_path, manifest)
        verified = load_live_state(root / "production_state", trading_date, cadence)
        latest_path = root / "RATE_PRODUCTION_STATE_LATEST.json"
        latest = read_object(latest_path) if latest_path.exists() else None
        slot = (trading_date, cadence)
        if not latest or (latest.get("trading_date", ""), latest.get("cadence", "")) <= slot:
            atomic_write_json(latest_path, {"artifact": "RATE_PRODUCTION_STATE_LATEST", "validation_status": "PASS",
                "trading_date": trading_date, "cadence": cadence, "workflow_run_id": verified["manifest"]["workflow_run_id"],
                "workflow_job_id": verified["manifest"]["workflow_job_id"], "current_state_id": state_id,
                "current_state_hash": state["decision_payload_hash"], "previous_state_id": state["previous_state_id"],
                "live_state_evidence_path": (directory / PERSIST_NAME).as_posix()})
        out.update(validation_status="PASS", live_state_updated=True,
                   live_state_evidence_path=(directory / PERSIST_NAME).as_posix(), current_state_id=state_id,
                   current_state_hash=state["decision_payload_hash"],
                   checks={"complete_state": True, "previous_state_binding": True, "ledger_history_preserved": True},
                   idempotency_result="IDEMPOTENT_NOOP" if already_complete else "PERSISTED")
    except (RuntimeError, OSError, ValueError, KeyError, TypeError) as exc:
        out["blocking_reason"] = str(exc)
    if evidence_output:
        atomic_write_json(Path(evidence_output), out)
    return out


def main():
    parser = argparse.ArgumentParser(description="Publish complete scheduled production state without fallback.")
    parser.add_argument("--persist-evidence", required=True)
    parser.add_argument("--trading-date", required=True)
    parser.add_argument("--cadence", required=True, choices=sorted(CADENCE_DIR))
    parser.add_argument("--artifacts-root", default="artifacts")
    parser.add_argument("--state-root", required=True)
    parser.add_argument("--workflow-run-id")
    parser.add_argument("--workflow-job-id")
    parser.add_argument("--evidence-output")
    args = parser.parse_args()
    out = publish_state(persist_evidence_path=args.persist_evidence, trading_date=args.trading_date,
                        cadence=args.cadence, artifacts_root=args.artifacts_root, state_root=args.state_root,
                        workflow_run_id=args.workflow_run_id, workflow_job_id=args.workflow_job_id,
                        evidence_output=args.evidence_output)
    print(json.dumps(out, ensure_ascii=False, sort_keys=True))
    return 0 if out["validation_status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())

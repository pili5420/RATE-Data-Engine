from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.cer074_acceptance import atomic_write_json, load_json

CADENCE_DIR = {"07:30": "0730", "09:30": "0930", "12:00": "1200", "19:30": "1930"}
REQUIRED = {"07:30": "RATE_CER075_PERSIST_RESULT_EVIDENCE", "09:30": "RATE_CER076_PERSIST_RESULT_EVIDENCE", "12:00": "RATE_CER077_PERSIST_RESULT_EVIDENCE", "19:30": "RATE_CER078_PERSIST_RESULT_EVIDENCE"}


def publish_state(*, persist_evidence_path: str | Path, trading_date: str, cadence: str, artifacts_root: str | Path = "artifacts", workflow_run_id: str | None = None, workflow_job_id: str | None = None, evidence_output: str | Path | None = None) -> dict[str, Any]:
    root = Path(artifacts_root)
    payload = load_json(persist_evidence_path)
    state_entry = (payload.get("persist_result") or {}).get("state_entry")
    checks = {
        "validation_status": payload.get("validation_status") == "PASS",
        "artifact_contract": payload.get("artifact") == REQUIRED[cadence],
        "persisted_or_idempotent": (payload.get("persist_result") or {}).get("status") in {"PERSISTED", "IDEMPOTENT_NOOP"},
        "state_entry_present": isinstance(state_entry, dict),
        "trading_date": isinstance(state_entry, dict) and state_entry.get("trading_date") == trading_date,
        "cadence": isinstance(state_entry, dict) and (state_entry.get("cadence") or state_entry.get("decision_time")) == cadence,
    }
    out = {
        "artifact": "RATE_PRODUCTION_STATE_LIVE_UPDATE_EVIDENCE",
        "validation_status": "PASS" if all(checks.values()) else "BLOCKED",
        "workflow_run_id": workflow_run_id,
        "workflow_job_id": workflow_job_id,
        "trading_date": trading_date,
        "cadence": cadence,
        "checks": checks,
        "live_state_updated": False,
    }
    if out["validation_status"] != "PASS":
        out["blocking_reason"] = "PRODUCTION_PERSIST_EVIDENCE_NOT_PASS"
        if evidence_output:
            atomic_write_json(Path(evidence_output), out)
        return out
    live_path = root / "production_state" / "live" / trading_date / CADENCE_DIR[cadence] / "RATE_PRODUCTION_PERSIST_RESULT_EVIDENCE.json"
    latest_path = root / "RATE_PRODUCTION_STATE_LATEST.json"
    atomic_write_json(live_path, payload)
    latest = {
        "artifact": "RATE_PRODUCTION_STATE_LATEST",
        "validation_status": "PASS",
        "trading_date": trading_date,
        "cadence": cadence,
        "workflow_run_id": workflow_run_id,
        "workflow_job_id": workflow_job_id,
        "current_state_id": payload.get("current_state_id"),
        "current_state_hash": payload.get("current_state_hash"),
        "previous_state_id": payload.get("previous_state_id"),
        "live_state_evidence_path": str(live_path).replace("\\", "/"),
    }
    atomic_write_json(latest_path, latest)
    out.update({"live_state_updated": True, "live_state_evidence_path": latest["live_state_evidence_path"], "current_state_id": latest["current_state_id"], "current_state_hash": latest["current_state_hash"]})
    if evidence_output:
        atomic_write_json(Path(evidence_output), out)
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="Publish validated production persist evidence into the live production state store.")
    parser.add_argument("--persist-evidence", required=True)
    parser.add_argument("--trading-date", required=True)
    parser.add_argument("--cadence", required=True, choices=sorted(CADENCE_DIR))
    parser.add_argument("--artifacts-root", default="artifacts")
    parser.add_argument("--workflow-run-id")
    parser.add_argument("--workflow-job-id")
    parser.add_argument("--evidence-output")
    args = parser.parse_args()
    out = publish_state(persist_evidence_path=args.persist_evidence, trading_date=args.trading_date, cadence=args.cadence, artifacts_root=args.artifacts_root, workflow_run_id=args.workflow_run_id, workflow_job_id=args.workflow_job_id, evidence_output=args.evidence_output)
    print(json.dumps(out, ensure_ascii=False, sort_keys=True))
    return 0 if out["validation_status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())

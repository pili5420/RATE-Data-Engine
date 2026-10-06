"""Prepare a MAIN-authorized canonical decision; publishers own live writes."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.cer074_acceptance import atomic_write_json
from src.phase2_production import main_authority, prepare_bundle_state, persist_prepared_state, latest_predecessor
from src.production_live_state import ARTIFACTS, require
from src.thin_work_manifest import build_shadow_manifest, validate_shadow_manifest


def preflight_manifest(path, bundle, authority):
    manifest = build_shadow_manifest(production_artifact_path=path, cadence=bundle["cadence"],
        run_id=authority["run_id"], event=authority["event"], commit_sha=authority["commit_sha"],
        market_date=bundle["trading_date"])
    gate = validate_shadow_manifest(manifest, expected_run_id=authority["run_id"],
        expected_commit_sha=authority["commit_sha"], expected_production_snapshot_id=bundle["production_snapshot_id"])
    require(gate["validation_status"] == "PASS", "PHASE2_THIN_MANIFEST_NOT_PASS:" + str(gate.get("errors")))
    return gate


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--cadence", required=True, choices=sorted(ARTIFACTS))
    parser.add_argument("--source-bundle", required=True)
    parser.add_argument("--canonical-state-root", default="artifacts/production_state")
    parser.add_argument("--state-root", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--actions-job-id", required=True)
    parser.add_argument("--expected-previous-state-evidence", required=True)
    args = parser.parse_args()
    out = {"artifact": "RATE_PHASE2_RUNTIME_EVIDENCE", "validation_status": "FAIL_CLOSED",
           "live_state_mutation": 0, "production_state_latest_mutation": 0, "fallback_used": False}
    try:
        authority = main_authority()
        import os
        require(args.actions_job_id == os.getenv("ACTIONS_JOB_ID"), "PHASE2_JOB_ID_BINDING_INVALID")
        bundle = json.loads(Path(args.source_bundle).read_bytes())
        require(bundle["cadence"] == args.cadence and bundle["input_material"]["runtime_authority"] == authority,
                "PHASE2_RUNTIME_AUTHORITY_BINDING_INVALID")
        previous = latest_predecessor(args.canonical_state_root, bundle["trading_date"], args.cadence)[2]
        require(previous["path"].resolve() == Path(args.expected_previous_state_evidence).resolve(),
                "PHASE2_EXTERNAL_PREDECESSOR_BINDING_INVALID")
        state = prepare_bundle_state(bundle, state_root=args.canonical_state_root)
        out["thin_manifest_validation"] = preflight_manifest(args.source_bundle, bundle, authority)
        persist = persist_prepared_state(state, args.state_root, args.cadence)
        atomic_write_json(Path(args.output_dir) / (ARTIFACTS[args.cadence] + ".json"), persist)
        out.update(validation_status="PASS", current_state_id=state["current_state_id"],
                   current_state_hash=state["decision_payload_hash"])
    except (RuntimeError, OSError, ValueError, KeyError, TypeError) as exc:
        out["blocking_reason"] = str(exc)
    atomic_write_json(Path(args.output_dir) / "RATE_PHASE2_RUNTIME_EVIDENCE.json", out)
    print(json.dumps(out, sort_keys=True))
    return 0 if out["validation_status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())

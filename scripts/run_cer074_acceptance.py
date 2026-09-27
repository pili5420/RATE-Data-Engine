from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.cer074_acceptance import (
    AS_OF_DATE,
    BOOTSTRAP_RESOLUTION,
    CER073_SOURCE_BUNDLE_HASH,
    FUNDAMENTAL_HASH,
    HISTORICAL_STATE_DIGEST,
    MAIN_HEAD,
    PRIOR_STAGE_DIGEST,
    PREVIOUS_STAGING_HEAD,
    build_artifacts,
    load_json,
    atomic_write_json,
)

ARTIFACT_NAMES = {
    "RATE_CER074_PRODUCTION_INPUT_SNAPSHOT_EVIDENCE.json": "RATE_CER074_PRODUCTION_INPUT_SNAPSHOT_EVIDENCE",
    "RATE_CER074_DECISION_STATE_DRYRUN_A.json": "RATE_CER074_DECISION_STATE_DRYRUN_A",
    "RATE_CER074_DECISION_STATE_DRYRUN_B.json": "RATE_CER074_DECISION_STATE_DRYRUN_B",
    "RATE_CER074_PERSISTED_DECISION_STATE_EVIDENCE.json": "RATE_CER074_PERSISTED_DECISION_STATE_EVIDENCE",
    "RATE_CER074_PERSISTENCE_IDEMPOTENCY_EVIDENCE.json": "RATE_CER074_PERSISTENCE_IDEMPOTENCY_EVIDENCE",
    "RATE_CER074_LINEAGE_ACCEPTANCE_EVIDENCE.json": "RATE_CER074_LINEAGE_ACCEPTANCE_EVIDENCE",
}


def git_value(args: list[str]) -> str | None:
    try:
        return subprocess.run(["git", *args], capture_output=True, text=True, check=True).stdout.strip()
    except Exception:
        return None


def init_fail_closed(output_dir: Path, *, reason: str = "NOT_RUN") -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    common = {
        "validation_status": "NOT_RUN" if reason == "NOT_RUN" else "FAIL",
        "trading_date": AS_OF_DATE,
        "source_bundle_hash": CER073_SOURCE_BUNDLE_HASH,
        "fundamental_analytical_hash": FUNDAMENTAL_HASH,
        "prior_stage_package_digest": PRIOR_STAGE_DIGEST,
        "historical_state_digest": HISTORICAL_STATE_DIGEST,
        "previous_staging_head": PREVIOUS_STAGING_HEAD,
        "previous_state_resolution": None,
        "previous_state_id": None,
        "production_snapshot_created": "NO",
        "production_decision_state_persisted": "NO",
        "rate_live_e2e_enabled": "YES_FOR_CER074_ACCEPTANCE_ONLY",
        "recurring_production_scheduler_enabled": False,
        "main_head": MAIN_HEAD,
        "main_modified": False,
        "remaining_blockers": [] if reason == "NOT_RUN" else [reason],
    }
    for filename, artifact in ARTIFACT_NAMES.items():
        atomic_write_json(output_dir / filename, {"artifact": artifact, **common})


def main() -> int:
    parser = argparse.ArgumentParser(description="RATE CER-074 first 07:30 production snapshot/state acceptance")
    parser.add_argument("--source-bundle", required=True)
    parser.add_argument("--output-dir", default="artifacts/cer074")
    parser.add_argument("--state-root", default="data/production/cer074_acceptance")
    parser.add_argument("--run-head-sha", default=os.getenv("GITHUB_SHA"))
    parser.add_argument("--actions-run-id", default=os.getenv("GITHUB_RUN_ID"))
    parser.add_argument("--actions-job-id", default=os.getenv("GITHUB_JOB"))
    parser.add_argument("--reset-state-root", action="store_true")
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    state_root = Path(args.state_root)
    init_fail_closed(output_dir)
    try:
        if args.reset_state_root and state_root.exists():
            resolved = state_root.resolve()
            allowed = (Path.cwd() / "data" / "production").resolve()
            if allowed not in resolved.parents and resolved != allowed:
                raise RuntimeError("PRODUCTION_NAMESPACE_GUARD")
            shutil.rmtree(state_root)
        bundle = load_json(args.source_bundle)
        artifacts = build_artifacts(
            bundle,
            state_root,
            run_head_sha=args.run_head_sha,
            actions_run_id=args.actions_run_id,
            actions_job_id=args.actions_job_id,
        )
        for filename, payload in artifacts.items():
            atomic_write_json(output_dir / filename, payload)
        lineage = artifacts["RATE_CER074_LINEAGE_ACCEPTANCE_EVIDENCE.json"]
        terminal_pass = all([
            lineage.get("cer073_binding") == "PASS",
            lineage.get("production_snapshot_created") == "YES",
            bool(lineage.get("input_snapshot_id")),
            lineage.get("production_snapshot_coverage") == "30/30",
            lineage.get("first_production_bootstrap_semantics") == "PASS",
            lineage.get("prior_stage_binding") == "30/30",
            lineage.get("pending_snapshot_lineage_count") == 0,
            lineage.get("decision_state_coverage") == "30/30",
            lineage.get("model_freeze_integrity") == "PASS",
            lineage.get("decision_state_determinism") == "PASS",
            lineage.get("dry_run_a_persist_count") == 0,
            lineage.get("dry_run_b_persist_count") == 0,
            lineage.get("first_persist_new_record_count") == 1,
            lineage.get("replay_new_record_count") == 0,
            lineage.get("production_state_idempotency") == "PASS",
            lineage.get("decision_state_lineage") == "PASS",
            lineage.get("main_modified") is False,
        ])
        print(json.dumps({
            "validation_status": "PASS" if terminal_pass else "FAIL",
            "input_snapshot_id": lineage.get("input_snapshot_id"),
            "decision_state_id": artifacts["RATE_CER074_DECISION_STATE_DRYRUN_A.json"].get("decision_state_id"),
            "previous_state_resolution": BOOTSTRAP_RESOLUTION,
            "previous_state_id": None,
        }, ensure_ascii=False, sort_keys=True))
        return 0 if terminal_pass else 1
    except Exception as exc:
        init_fail_closed(output_dir, reason=str(exc))
        print(json.dumps({"validation_status": "BLOCKED", "blocking_reason": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

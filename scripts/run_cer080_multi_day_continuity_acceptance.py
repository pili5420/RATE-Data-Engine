from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.cer074_acceptance import atomic_write_json, load_json
from src.cer080_multi_day_continuity import build_cer080_artifacts, write_fail_closed


def main() -> int:
    ap = argparse.ArgumentParser(description="RATE CER-080 multi-day production continuity acceptance")
    ap.add_argument("--source-bundle", required=True)
    ap.add_argument("--cer078-persisted-evidence", required=True)
    ap.add_argument("--output-dir", default="artifacts/cer080")
    ap.add_argument("--state-root", default="data/production/cer080_multi_day_continuity_acceptance")
    ap.add_argument("--run-head-sha", default=os.getenv("GITHUB_SHA"))
    ap.add_argument("--actions-run-id", default=os.getenv("GITHUB_RUN_ID"))
    ap.add_argument("--actions-job-id", default=os.getenv("ACTIONS_JOB_ID") or os.getenv("GITHUB_JOB"))
    ap.add_argument("--event-name", default=os.getenv("GITHUB_EVENT_NAME"))
    ap.add_argument("--reset-state-root", action="store_true")
    args = ap.parse_args()

    out = Path(args.output_dir)
    out.mkdir(parents=True, exist_ok=True)
    write_fail_closed(out, run_head_sha=args.run_head_sha, actions_run_id=args.actions_run_id, actions_job_id=args.actions_job_id, event_name=args.event_name)
    try:
        root = Path(args.state_root)
        if args.reset_state_root and root.exists():
            allowed = (Path.cwd() / "data" / "production").resolve()
            resolved = root.resolve()
            if allowed not in resolved.parents and resolved != allowed:
                raise RuntimeError("PRODUCTION_NAMESPACE_GUARD")
            shutil.rmtree(root)
        artifacts = build_cer080_artifacts(
            source_bundle=load_json(args.source_bundle),
            cer078_persisted=load_json(args.cer078_persisted_evidence),
            state_root=root,
            run_head_sha=args.run_head_sha,
            actions_run_id=args.actions_run_id,
            actions_job_id=args.actions_job_id,
            event_name=args.event_name,
        )
        for filename, payload in artifacts.items():
            atomic_write_json(out / filename, payload)
        persist = artifacts["RATE_CER080_PERSIST_RESULT_EVIDENCE.json"]
        replay = artifacts["RATE_CER080_REPLAY_IDEMPOTENCY_EVIDENCE.json"]
        failure = artifacts["RATE_CER080_FAILURE_GATE_EVIDENCE.json"]
        terminal = replay["production_state_idempotency"] == "PASS" and failure["failure_closed_behavior"] == "PASS"
        print(json.dumps({
            "validation_status": "PASS" if terminal else "FAIL",
            "previous_trading_date": persist["previous_trading_date"],
            "current_trading_date": persist["current_trading_date"],
            "current_state_id": persist["current_state_id"],
            "current_state_hash": persist["current_state_hash"],
            "first_persist_new_record_count": persist["first_persist_new_record_count"],
            "replay_new_record_count": replay["replay_new_record_count"],
        }, sort_keys=True))
        return 0 if terminal else 1
    except Exception as exc:
        write_fail_closed(out, reason=str(exc), run_head_sha=args.run_head_sha, actions_run_id=args.actions_run_id, actions_job_id=args.actions_job_id, event_name=args.event_name)
        print(json.dumps({"validation_status": "BLOCKED", "blocking_reason": str(exc)}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

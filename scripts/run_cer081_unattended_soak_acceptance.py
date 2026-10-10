
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.cer074_acceptance import atomic_write_json, load_json
from src.cer081_unattended_soak import APPROVED_RATE_SOURCE_URL, build_cer081_artifacts, write_fail_closed


def main() -> int:
    ap = argparse.ArgumentParser(description="RATE CER-081 unattended multi-day production soak acceptance")
    ap.add_argument("--cer080-persisted-evidence", required=True)
    ap.add_argument("--scheduled-runs-json")
    ap.add_argument("--rate-source-url", default=os.getenv("RATE_SOURCE_URL") or APPROVED_RATE_SOURCE_URL)
    ap.add_argument("--output-dir", default="artifacts/cer081")
    ap.add_argument("--run-head-sha", default=os.getenv("GITHUB_SHA"))
    ap.add_argument("--actions-run-id", default=os.getenv("GITHUB_RUN_ID"))
    ap.add_argument("--actions-job-id", default=os.getenv("ACTIONS_JOB_ID") or os.getenv("GITHUB_JOB"))
    ap.add_argument("--event-name", default=os.getenv("GITHUB_EVENT_NAME"))
    args = ap.parse_args()
    out = Path(args.output_dir)
    out.mkdir(parents=True, exist_ok=True)
    write_fail_closed(out, run_head_sha=args.run_head_sha, actions_run_id=args.actions_run_id, actions_job_id=args.actions_job_id, event_name=args.event_name)
    try:
        scheduled = []
        if args.scheduled_runs_json:
            scheduled = load_json(args.scheduled_runs_json)
        dependencies = load_json(Path(__file__).resolve().parents[1] / "config/RATE_EXTERNAL_PRODUCTION_DEPENDENCIES.json")
        dependency = next(item for item in dependencies["dependencies"]
            if item["dependency_id"] == "EXTERNAL_AUTHORIZED_INTRADAY_FEED_DEPENDENCY")
        artifacts = build_cer081_artifacts(
            cer080_persisted=load_json(args.cer080_persisted_evidence),
            scheduled_runs_raw=scheduled,
            rate_source_url=args.rate_source_url,
            run_head_sha=args.run_head_sha,
            actions_run_id=args.actions_run_id,
            actions_job_id=args.actions_job_id,
            event_name=args.event_name,
            current_dependency=dependency,
        )
        for filename, payload in artifacts.items():
            atomic_write_json(out / filename, payload)
        summary = artifacts["RATE_CER081_SOAK_SUMMARY.json"]
        print(json.dumps({
            "validation_status": summary["final_result"],
            "completion_status": summary["completion_status"],
            "soak_start_date": summary["soak_start_date"],
            "soak_end_date": summary["soak_end_date"],
            "trading_days_tested": summary["trading_days_tested"],
            "expected_cadence_runs": summary["expected_cadence_runs"],
            "successful_cadence_runs": summary["successful_cadence_runs"],
            "duplicate_production_record_count": summary["duplicate_production_record_count"],
            "unrecovered_failure_count": summary["unrecovered_failure_count"],
            "remaining_blockers": summary["remaining_blockers"],
        }, sort_keys=True))
        return 0 if summary["final_result"] == "PASS" else 1
    except Exception as exc:
        write_fail_closed(out, reason=str(exc), run_head_sha=args.run_head_sha, actions_run_id=args.actions_run_id, actions_job_id=args.actions_job_id, event_name=args.event_name)
        print(json.dumps({"validation_status": "BLOCKED", "blocking_reason": str(exc)}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

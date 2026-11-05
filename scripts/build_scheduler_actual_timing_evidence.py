from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.cer081_scheduler_actual_timing import build_actual_timing_evidence


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--github-run-json", required=True)
    p.add_argument("--cadence", required=True)
    p.add_argument("--trading-date", required=True)
    p.add_argument("--event-schedule", required=True)
    p.add_argument("--workflow-path", required=True)
    p.add_argument("--expected-run-id", required=True)
    p.add_argument("--expected-head-sha", required=True)
    p.add_argument("--output", required=True)
    args = p.parse_args()

    run_api = json.loads(Path(args.github_run_json).read_text(encoding="utf-8"))
    evidence = build_actual_timing_evidence(
        run_api,
        cadence=args.cadence,
        trading_date=args.trading_date,
        event_schedule=args.event_schedule,
        workflow_path=args.workflow_path,
        expected_run_id=args.expected_run_id,
        expected_head_sha=args.expected_head_sha,
    )
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()

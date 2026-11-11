"""Fail closed before official retrieval when an actual scheduled run is late."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.cer081_scheduler_actual_timing import (
    DEFAULT_BLOCKING_DELAY_SECONDS, SchedulerActualTimingError,
    build_actual_timing_evidence,
)


def evaluate(run_api: dict, timing: dict, *, cadence: str, trading_date: str,
             run_id: str, head_sha: str, event_schedule: str, workflow_path: str) -> dict:
    if not isinstance(run_api, dict) or not isinstance(timing, dict):
        return {"artifact": "RATE_PRODUCTION_SCHEDULER_PREACQUISITION_GATE_V1",
            "validation_status": "FAIL_CLOSED", "production_credit": 0,
            "blocking_reason": "SCHEDULER_TIMING_SOURCE_INVALID", "fallback_used": False}
    result = {
        "artifact": "RATE_PRODUCTION_SCHEDULER_PREACQUISITION_GATE_V1",
        "validation_status": "FAIL_CLOSED", "production_credit": 0,
        "workflow_run_id": str(run_id), "cadence": cadence,
        "trading_date": trading_date, "blocking_delay_seconds": DEFAULT_BLOCKING_DELAY_SECONDS,
        "fallback_used": False,
        "run_api_sha256": hashlib.sha256(json.dumps(run_api, sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
        "timing_sha256": hashlib.sha256(json.dumps(timing, sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
    }
    try:
        expected = build_actual_timing_evidence(run_api, cadence=cadence,
            trading_date=trading_date, event_schedule=event_schedule,
            workflow_path=workflow_path, expected_run_id=run_id, expected_head_sha=head_sha)
        created = datetime.fromisoformat(expected["actions_created_at"].replace("Z", "+00:00"))
        started = datetime.fromisoformat(expected["actions_run_started_at"].replace("Z", "+00:00"))
        if created > started:
            raise SchedulerActualTimingError("SCHEDULER_CREATED_AFTER_START")
        if timing != expected:
            raise SchedulerActualTimingError("SCHEDULER_TIMING_EVIDENCE_MISMATCH")
        if expected["delayed_execution_blocking"]:
            raise SchedulerActualTimingError("SCHEDULER_BLOCKING_DELAY")
        result.update(validation_status="PASS", production_credit=0,
            scheduler_start_delay_seconds=expected["scheduler_start_delay_seconds"],
            expected_scheduled_at_utc=expected["expected_scheduled_at_utc"])
    except (SchedulerActualTimingError, KeyError, TypeError, ValueError) as exc:
        result["blocking_reason"] = str(exc)
        if isinstance(timing, dict) and isinstance(timing.get("scheduler_start_delay_seconds"), (int, float)):
            result["observed_delay_seconds"] = timing["scheduler_start_delay_seconds"]
    return result


def main() -> int:
    p = argparse.ArgumentParser()
    for name in ("run-api", "timing", "cadence", "trading-date", "run-id",
                 "head-sha", "event-schedule", "workflow-path", "output"):
        p.add_argument("--" + name, required=True)
    args = p.parse_args()
    output = Path(args.output)
    try:
        run_api = json.loads(Path(args.run_api).read_text(encoding="utf-8"))
        timing = json.loads(Path(args.timing).read_text(encoding="utf-8"))
        result = evaluate(run_api, timing, cadence=args.cadence,
            trading_date=args.trading_date, run_id=args.run_id,
            head_sha=args.head_sha, event_schedule=args.event_schedule,
            workflow_path=args.workflow_path)
    except (OSError, ValueError, TypeError) as exc:
        result = {"artifact": "RATE_PRODUCTION_SCHEDULER_PREACQUISITION_GATE_V1",
            "validation_status": "FAIL_CLOSED", "production_credit": 0,
            "blocking_reason": "SCHEDULER_TIMING_SOURCE_UNREADABLE:" + type(exc).__name__,
            "fallback_used": False}
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, sort_keys=True))
    return 0 if result["validation_status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())

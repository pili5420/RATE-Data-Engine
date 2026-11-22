"""Production schedule pre-admission: fail closed before any source acquisition.

Only existing GitHub native schedule events are admissible. External trigger
options remain DESIGN ONLY until separately authorized, deployed and qualified.
"""
from __future__ import annotations

import argparse
from datetime import datetime
import json
import math
import os
from pathlib import Path
import sys
from typing import Mapping, Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.cer081_scheduler_actual_timing import (
    CADENCE_CRONS, CADENCE_WORKFLOWS, expected_slot_utc,
    SchedulerActualTimingError, _parse_utc,
)


class SchedulerPreAdmissionBlocked(RuntimeError):
    pass


def _require(condition: bool, reason: str) -> None:
    if not condition:
        raise SchedulerPreAdmissionBlocked(reason)


def _safe_utc(value: Any, reason: str) -> datetime:
    try:
        return _parse_utc(value, reason)
    except (SchedulerActualTimingError, ValueError, TypeError):
        raise SchedulerPreAdmissionBlocked(reason) from None


def _seconds_equal(actual: Any, expected: float) -> bool:
    return (type(actual) in (int, float)
            and math.isfinite(actual)
            and abs(actual - expected) < 0.000001)


def qualify_schedule_before_sources(evidence: Mapping[str, Any], *,
                                    cadence: str, trading_date: str,
                                    run_id: str, head_sha: str,
                                    job_id: str, job_name: str) -> dict:
    """Admission depends on real GitHub run + job times, not report PASS status.

    Missing, unbound, replayed, skipped or late jobs are always rejected.
    A passing offline test is never a Production admission permit.
    """
    _require(cadence in CADENCE_CRONS, "P0_CADENCE_NOT_APPROVED")
    _require(isinstance(run_id, str) and run_id.isdigit()
             and isinstance(job_id, str) and job_id.isdigit()
             and isinstance(head_sha, str) and len(head_sha) == 40
             and all(ch in "0123456789abcdef" for ch in head_sha),
             "P0_RUN_JOB_SHA_IDENTITY_INVALID")
    _require(job_name == "production-" + cadence.replace(":", ""),
             "P0_JOB_NAME_MISMATCH")
    _require(evidence.get("artifact") == "RATE_CER081_SCHEDULER_ACTUAL_TIMING_EVIDENCE_V1"
             and evidence.get("validation_status") == "PASS"
             and evidence.get("source") == "GITHUB_ACTIONS_RUN_API_PLUS_RUNTIME_CONTEXT"
             and evidence.get("event_name") == "schedule"
             and evidence.get("event_schedule") == CADENCE_CRONS[cadence]
             and evidence.get("workflow_path") == CADENCE_WORKFLOWS[cadence]
             and evidence.get("cadence") == cadence
             and evidence.get("trading_date") == trading_date
             and str(evidence.get("workflow_run_id")) == run_id
             and evidence.get("run_head_sha") == head_sha
             and type(evidence.get("run_attempt")) is int
             and evidence["run_attempt"] == 1,
             "P0_SCHEDULER_RUN_BINDING_INVALID")
    _require(evidence.get("blocking_delay_seconds") == 900
             and evidence.get("nearest_slot_inference_used") is False
             and evidence.get("wall_clock_only_evidence") is False
             and evidence.get("post_hoc_date_inference_used") is False,
             "P0_SCHEDULER_CONTRACT_CHANGED")
    nominal = expected_slot_utc(trading_date, cadence)
    _require(evidence.get("expected_scheduled_at_utc")
             == nominal.isoformat().replace("+00:00", "Z"),
             "P0_NOMINAL_SLOT_BINDING_INVALID")
    run_created = _safe_utc(evidence.get("actions_created_at"), "P0_RUN_CREATED_AT_MISSING")
    run_started = _safe_utc(evidence.get("actions_run_started_at"), "P0_RUN_STARTED_AT_MISSING")
    run_delay = (run_started - nominal).total_seconds()
    _require(run_created <= run_started and run_delay >= 0
             and _seconds_equal(evidence.get("scheduler_start_delay_seconds"), run_delay),
             "P0_RUN_TIMESTAMP_INCONSISTENT")
    observation = evidence.get("p0_scheduler_diagnostics")
    _require(isinstance(observation, Mapping)
             and observation.get("schema_id") == "RATE-P0-SCHEDULER-DIAGNOSTIC-V1"
             and observation.get("github_job_timestamp_status") == "PASS"
             and observation.get("observability_status") == "PASS"
             and observation.get("github_job_timestamp_provenance") == "GITHUB_ACTIONS_JOB_API"
             and observation.get("github_job_id") == job_id
             and observation.get("github_job_name") == job_name
             and observation.get("github_run_timestamp_provenance") == "GITHUB_ACTIONS_RUN_API"
             and observation.get("nominal_cron_time_utc") == evidence.get("expected_scheduled_at_utc")
             and observation.get("github_run_started_at") == evidence.get("actions_run_started_at")
             and observation.get("github_run_created_at") == evidence.get("actions_created_at"),
             "P0_JOB_API_BINDING_INVALID")
    job_started = _safe_utc(observation.get("github_job_started_at"), "P0_JOB_STARTED_AT_MISSING")
    job_delay = (job_started - nominal).total_seconds()
    _require(job_started >= run_started and _seconds_equal(
        observation.get("job_start_lag_seconds"),
        (job_started - run_started).total_seconds()),
        "P0_JOB_TIMESTAMP_INCONSISTENT")
    _require(evidence.get("delayed_execution_blocking") is (run_delay > 900),
             "P0_DELAY_FLAG_INCONSISTENT")
    _require(0 <= job_delay <= 900 and run_delay <= 900,
             "P0_SCHEDULER_START_DELAY_EXCEEDED_900S")
    return {
        "admission": "PASS", "cadence": cadence, "trading_date": trading_date,
        "workflow_run_id": run_id, "workflow_job_id": job_id,
        "run_head_sha": head_sha, "job_delay_seconds": job_delay,
        "run_delay_seconds": run_delay, "blocking_delay_seconds": 900,
        "publication_credit": "NOT_GRANTED_BY_PRE_ADMISSION",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence", required=True)
    parser.add_argument("--cadence", required=True)
    parser.add_argument("--trading-date", required=True)
    parser.add_argument("--expected-run-id", required=True)
    parser.add_argument("--expected-head-sha", required=True)
    parser.add_argument("--expected-job-id", required=True)
    parser.add_argument("--expected-job-name", required=True)
    args = parser.parse_args()
    try:
        _require(os.getenv("GITHUB_ACTIONS") == "true"
                 and os.getenv("GITHUB_REPOSITORY") == "pili5420/RATE-Data-Engine"
                 and os.getenv("GITHUB_EVENT_NAME") == "schedule"
                 and os.getenv("GITHUB_REF") == "refs/heads/main"
                 and os.getenv("GITHUB_RUN_ATTEMPT") == "1"
                 and os.getenv("GITHUB_RUN_ID") == args.expected_run_id
                 and os.getenv("GITHUB_SHA") == args.expected_head_sha
                 and os.getenv("GITHUB_JOB") == args.expected_job_name,
                 "P0_PRODUCTION_RUNTIME_IDENTITY_INVALID")
        evidence = json.loads(Path(args.evidence).read_text(encoding="utf-8"))
        result = qualify_schedule_before_sources(
            evidence, cadence=args.cadence, trading_date=args.trading_date,
            run_id=args.expected_run_id, head_sha=args.expected_head_sha,
            job_id=args.expected_job_id, job_name=args.expected_job_name)
    except (SchedulerPreAdmissionBlocked, SchedulerActualTimingError,
            OSError, TypeError, KeyError, ValueError, json.JSONDecodeError) as error:
        reason = str(error) if isinstance(error, SchedulerPreAdmissionBlocked) else "P0_SCHEDULER_PRE_ADMISSION_EVIDENCE_INVALID"
        print(json.dumps({"admission": "BLOCK", "reason": reason, "production_state_mutation": 0}))
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

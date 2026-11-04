from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Mapping

CADENCE_CRONS = {
    "07:30": "30 23 * * 0-4",
    "09:30": "30 1 * * 1-5",
    "12:00": "0 4 * * 1-5",
    "19:30": "30 11 * * 1-5",
}
CADENCE_WORKFLOWS = {
    "07:30": ".github/workflows/rate_production_0730_scheduler.yml",
    "09:30": ".github/workflows/rate_production_0930_scheduler.yml",
    "12:00": ".github/workflows/rate_production_1200_scheduler.yml",
    "19:30": ".github/workflows/rate_production_1930_scheduler.yml",
}
DEFAULT_BLOCKING_DELAY_SECONDS = 900
TAIPEI = timezone(timedelta(hours=8), name="Asia/Taipei")


class SchedulerActualTimingError(RuntimeError):
    pass


def _require(ok: bool, reason: str) -> None:
    if not ok:
        raise SchedulerActualTimingError(reason)


def _parse_utc(value: Any, reason: str) -> datetime:
    _require(isinstance(value, str) and value, reason)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise SchedulerActualTimingError(reason) from exc
    _require(parsed.tzinfo is not None, reason)
    return parsed


def expected_slot_utc(trading_date: str, cadence: str) -> datetime:
    _require(cadence in CADENCE_CRONS, "SCHEDULER_TIMING_UNKNOWN_CADENCE")
    try:
        local = datetime.fromisoformat(f"{trading_date}T{cadence}:00").replace(tzinfo=TAIPEI)
    except ValueError as exc:
        raise SchedulerActualTimingError("SCHEDULER_TIMING_INVALID_TRADING_DATE") from exc
    return local.astimezone(timezone.utc)


def build_actual_timing_evidence(
    run_api: Mapping[str, Any],
    *,
    cadence: str,
    trading_date: str,
    event_schedule: str,
    workflow_path: str,
    expected_run_id: str,
    expected_head_sha: str,
    blocking_delay_seconds: int = DEFAULT_BLOCKING_DELAY_SECONDS,
) -> dict[str, Any]:
    _require(cadence in CADENCE_CRONS, "SCHEDULER_TIMING_UNKNOWN_CADENCE")
    _require(event_schedule == CADENCE_CRONS[cadence], "SCHEDULER_TIMING_EVENT_CRON_MISMATCH")
    _require(workflow_path == CADENCE_WORKFLOWS[cadence], "SCHEDULER_TIMING_WORKFLOW_PATH_MISMATCH")
    _require(str(run_api.get("id")) == str(expected_run_id), "SCHEDULER_TIMING_RUN_ID_MISMATCH")
    _require(run_api.get("event") == "schedule", "SCHEDULER_TIMING_NOT_SCHEDULE_EVENT")
    _require(run_api.get("path") == workflow_path, "SCHEDULER_TIMING_API_WORKFLOW_PATH_MISMATCH")
    _require(run_api.get("head_sha") == expected_head_sha, "SCHEDULER_TIMING_HEAD_SHA_MISMATCH")
    _require(int(run_api.get("run_attempt", 0)) == 1, "SCHEDULER_TIMING_RETRY_NOT_ALLOWED")

    created = _parse_utc(run_api.get("created_at"), "SCHEDULER_TIMING_CREATED_AT_MISSING")
    started = _parse_utc(run_api.get("run_started_at"), "SCHEDULER_TIMING_RUN_STARTED_AT_MISSING")
    slot = expected_slot_utc(trading_date, cadence)
    delay = int((started - slot).total_seconds())
    _require(delay >= 0, "SCHEDULER_TIMING_NEGATIVE_DELAY")
    _require(blocking_delay_seconds >= 0, "SCHEDULER_TIMING_INVALID_DELAY_POLICY")

    return {
        "artifact": "RATE_CER081_SCHEDULER_ACTUAL_TIMING_EVIDENCE_V1",
        "validation_status": "PASS",
        "source": "GITHUB_ACTIONS_RUN_API_PLUS_RUNTIME_CONTEXT",
        "workflow_run_id": str(expected_run_id),
        "run_attempt": 1,
        "run_head_sha": expected_head_sha,
        "event_name": "schedule",
        "event_schedule": event_schedule,
        "workflow_path": workflow_path,
        "trading_date": trading_date,
        "cadence": cadence,
        "expected_scheduled_at_utc": slot.isoformat().replace("+00:00", "Z"),
        "actions_created_at": created.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
        "actions_run_started_at": started.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
        "scheduler_start_delay_seconds": delay,
        "blocking_delay_seconds": blocking_delay_seconds,
        "delayed_execution_blocking": delay > blocking_delay_seconds,
        "nearest_slot_inference_used": False,
        "wall_clock_only_evidence": False,
        "post_hoc_date_inference_used": False,
        "binding_method": "RUN_ID + EVENT_SCHEDULE + RUNTIME_TRADING_DATE + ACTIONS_API_TIMESTAMPS",
    }


def summarize_actual_timing_evidence(
    scheduled_runs: list[Mapping[str, Any]],
    *,
    blocking_delay_seconds: int = DEFAULT_BLOCKING_DELAY_SECONDS,
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    for run in scheduled_runs:
        evidence = run.get("scheduler_actual_timing")
        run_id = str(run.get("workflow_run_id") or "")
        cadence = run.get("cadence")
        trading_date = run.get("trading_date")
        if not isinstance(evidence, Mapping):
            failures.append({"workflow_run_id": run_id, "reason": "MISSING_ACTUAL_TIMING_EVIDENCE"})
            continue
        required = (
            evidence.get("artifact") == "RATE_CER081_SCHEDULER_ACTUAL_TIMING_EVIDENCE_V1"
            and evidence.get("validation_status") == "PASS"
            and evidence.get("source") == "GITHUB_ACTIONS_RUN_API_PLUS_RUNTIME_CONTEXT"
            and str(evidence.get("workflow_run_id")) == run_id
            and evidence.get("event_name") == "schedule"
            and evidence.get("event_schedule") == CADENCE_CRONS.get(cadence)
            and evidence.get("workflow_path") == CADENCE_WORKFLOWS.get(cadence)
            and evidence.get("trading_date") == trading_date
            and evidence.get("cadence") == cadence
            and evidence.get("run_attempt") == 1
            and evidence.get("nearest_slot_inference_used") is False
            and evidence.get("wall_clock_only_evidence") is False
            and evidence.get("post_hoc_date_inference_used") is False
            and isinstance(evidence.get("scheduler_start_delay_seconds"), int)
        )
        if not required:
            failures.append({"workflow_run_id": run_id, "reason": "ACTUAL_TIMING_BINDING_INVALID"})
            continue
        row = dict(evidence)
        row["delayed_execution_blocking"] = row["scheduler_start_delay_seconds"] > blocking_delay_seconds
        rows.append(row)

    delays = [r["scheduler_start_delay_seconds"] for r in rows]
    complete = len(rows) == len(scheduled_runs) and bool(scheduled_runs) and not failures
    delayed = sum(1 for r in rows if r["delayed_execution_blocking"])
    return {
        "actual_timing_evidence": "PASS" if complete else "FAIL",
        "actual_timing_evidence_count": len(rows),
        "actual_timing_missing_or_invalid_count": len(failures),
        "delayed_execution_blocking_count": delayed,
        "blocking_delay_seconds": blocking_delay_seconds,
        "average_scheduler_delay_seconds": None if not delays else sum(delays) / len(delays),
        "max_scheduler_delay_seconds": None if not delays else max(delays),
        "timing_failures": failures,
        "timing_rows": rows,
    }

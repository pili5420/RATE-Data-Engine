"""SC-01 offline-only Google Cloud Scheduler/Run portability contracts.

No production admission or cloud API call is possible from this module.
An actual trusted identity verifier and authenticated Google API readback remain
mandatory before any production use. This module intentionally does not infer
a source date, a predecessor state, or a trading calendar.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
import hashlib
import json
import re
from typing import Any, Mapping

from src.cer081_scheduler_actual_timing import (
    CADENCE_CRONS, DEFAULT_BLOCKING_DELAY_SECONDS, expected_slot_utc,
)

CADENCES = ("07:30", "09:30", "12:00", "19:30")
BLOCKING_DELAY_SECONDS = DEFAULT_BLOCKING_DELAY_SECONDS
SCHEMA = "RATE-SC01-OFFLINE-SCHEDULE-CONTRACT-V1"
PROJECT_RE = re.compile(r"[a-z][a-z0-9-]{4,28}[a-z0-9]\Z")
EVENT_RE = re.compile(r"[A-Za-z0-9_.:-]{12,128}\Z")
SHA_RE = re.compile(r"[0-9a-f]{64}\Z")


class SC01Blocked(RuntimeError):
    """Fail-closed contract violation, not permission to retry production."""


def require(ok: bool, reason: str) -> None:
    if not ok:
        raise SC01Blocked(reason)


def _utc(raw: Any, reason: str) -> datetime:
    require(isinstance(raw, str) and bool(raw), reason)
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except (ValueError, TypeError) as exc:
        raise SC01Blocked(reason) from exc
    require(parsed.tzinfo is not None, reason)
    return parsed.astimezone(timezone.utc)


def _iso(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def _safe_str(obj: Mapping[str, Any], key: str) -> str:
    value = obj.get(key)
    require(isinstance(value, str) and bool(value.strip()), "SC01_REQUIRED_" + key.upper())
    return value


@dataclass(frozen=True)
class SlotContract:
    project: str
    region: str
    scheduler_job: str
    cloud_run_job: str
    cadence: str
    trading_date: str
    expected_slot_utc: str
    slot_key: str

    def as_dict(self) -> dict[str, str]:
        return dict(self.__dict__)


def make_slot(*, project: str, region: str, cadence: str,
              trading_date: str) -> SlotContract:
    """Nominal slot identity only; NOT a proof this is an actual market day."""
    require(isinstance(project, str) and PROJECT_RE.fullmatch(project) is not None,
            "SC01_PROJECT_INVALID")
    require(isinstance(region, str) and re.fullmatch(r"[a-z]+-[a-z]+[0-9]+", region) is not None,
            "SC01_REGION_INVALID")
    require(cadence in CADENCES and cadence in CADENCE_CRONS, "SC01_CADENCE_INVALID")
    try:
        iso_day = date.fromisoformat(trading_date).isoformat()
    except (ValueError, TypeError) as exc:
        raise SC01Blocked("SC01_TRADING_DATE_INVALID") from exc
    require(iso_day == trading_date, "SC01_TRADING_DATE_NONCANONICAL")
    nominal = expected_slot_utc(trading_date, cadence)
    scheduler = f"projects/{project}/locations/{region}/jobs/rate-v11-{cadence.replace(':', '')}"
    run = f"projects/{project}/locations/{region}/jobs/rate-v11-engine"
    key = f"{project}/{region}/{trading_date}/{cadence}"
    return SlotContract(project, region, scheduler, run, cadence, trading_date, _iso(nominal), key)


def assess_schedule_envelope(envelope: Mapping[str, Any], slot: SlotContract,
                             *, expected_audience: str,
                             expected_service_account: str) -> dict[str, Any]:
    """Checks untrusted claimed fields. NEVER equates matching fields to OIDC verification.

    A production proxy must verify the signed Google token, permitted service
    account, trusted transport and calendar independently. The returned verdict
    cannot authorize cloud invocations or state writes.
    """
    require(isinstance(envelope, Mapping), "SC01_ENVELOPE_INVALID")
    require(_safe_str(envelope, "scheduler_job") == slot.scheduler_job,
            "SC01_SCHEDULER_JOB_MISMATCH")
    require(_safe_str(envelope, "cloud_run_job") == slot.cloud_run_job,
            "SC01_CLOUD_RUN_JOB_MISMATCH")
    require(_safe_str(envelope, "cadence") == slot.cadence
            and _safe_str(envelope, "trading_date") == slot.trading_date,
            "SC01_SLOT_BINDING_MISMATCH")
    require(_safe_str(envelope, "audience") == expected_audience
            and expected_audience.startswith("https://"), "SC01_AUDIENCE_MISMATCH")
    require(_safe_str(envelope, "service_account") == expected_service_account
            and expected_service_account.endswith(".gserviceaccount.com"),
            "SC01_SERVICE_ACCOUNT_MISMATCH")
    require(_safe_str(envelope, "issuer") == "https://accounts.google.com",
            "SC01_ISSUER_MISMATCH")
    event = _safe_str(envelope, "event_id")
    nonce = _safe_str(envelope, "nonce")
    require(EVENT_RE.fullmatch(event) is not None and EVENT_RE.fullmatch(nonce) is not None,
            "SC01_EVENT_OR_NONCE_INVALID")
    # Offline contract refuses retries until separately approved authenticated
    # first-attempt reconciliation; the claimed field is not crypto proof.
    require(type(envelope.get("delivery_attempt")) is int and envelope["delivery_attempt"] == 1,
            "SC01_DELIVERY_ATTEMPT_INVALID")
    claimed_nominal = _utc(envelope.get("nominal_slot_utc"), "SC01_NOMINAL_SLOT_MISSING")
    require(_iso(claimed_nominal) == slot.expected_slot_utc, "SC01_NOMINAL_SLOT_MISMATCH")
    digest = hashlib.sha256(json.dumps({
        "event_id": event, "nonce": nonce, "slot_key": slot.slot_key,
        "scheduler_job": slot.scheduler_job, "cloud_run_job": slot.cloud_run_job,
    }, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    return {
        "schema": SCHEMA, "verdict": "OFFLINE_CONTRACT_MATCH_ONLY",
        "identity_crypto_verified": False, "calendar_verified": False,
        "production_permit": "NOT_ISSUED", "slot_key": slot.slot_key,
        "event_id": event, "nonce": nonce, "event_digest": digest,
        "delivery_attempt": envelope["delivery_attempt"],
    }


def assess_task_start(execution: Mapping[str, Any], task: Mapping[str, Any],
                      slot: SlotContract, *, expected_execution: str,
                      expected_task: str) -> dict[str, Any]:
    """Offline Cloud Run v2 API-shape check, not a trusted API/Production receipt.

    Timeliness uses actual *Task.startTime*, not Cloud Scheduler trigger time,
    execution creation, run-submitted time, or GitHub run-start time.
    """
    require(isinstance(execution, Mapping) and isinstance(task, Mapping),
            "SC01_TASK_EVIDENCE_MISSING")
    require(isinstance(expected_execution, str) and expected_execution.startswith(
        slot.cloud_run_job + "/executions/"), "SC01_EXECUTION_PARENT_INVALID")
    require(isinstance(expected_task, str) and expected_task.startswith(
        expected_execution + "/tasks/"), "SC01_TASK_PARENT_INVALID")
    require(execution.get("name") == expected_execution
            and task.get("name") == expected_task, "SC01_EXECUTION_TASK_ID_MISMATCH")
    require(execution.get("job") == slot.cloud_run_job,
            "SC01_EXECUTION_JOB_MISMATCH")
    require(task.get("execution") == expected_execution,
            "SC01_TASK_EXECUTION_MISMATCH")
    require(type(execution.get("taskCount")) is int and execution["taskCount"] == 1
            and type(task.get("taskIndex")) is int and task["taskIndex"] == 0
            and type(task.get("retried")) is int and task["retried"] == 0,
            "SC01_TASK_ATTEMPT_UNQUALIFIED")
    created = _utc(execution.get("createTime"), "SC01_EXECUTION_CREATED_AT_MISSING")
    started = _utc(execution.get("startTime"), "SC01_EXECUTION_STARTED_AT_MISSING")
    task_started = _utc(task.get("startTime"), "SC01_TASK_STARTED_AT_MISSING")
    nominal = _utc(slot.expected_slot_utc, "SC01_NOMINAL_SLOT_INVALID")
    require(created <= started <= task_started, "SC01_TASK_TIME_ORDER_INVALID")
    delay = (task_started - nominal).total_seconds()
    require(0 <= delay <= BLOCKING_DELAY_SECONDS,
            "SC01_TASK_START_DELAY_EXCEEDED_900S")
    return {
        "schema": "RATE-SC01-OFFLINE-TASK-TIMING-V1",
        "verdict": "OFFLINE_TIMESTAMP_BOUNDARY_PASS_ONLY",
        "production_permit": "NOT_ISSUED",
        "provider_api_provenance_verified": False,
        "slot_key": slot.slot_key, "execution_name": expected_execution,
        "task_name": expected_task,
        "nominal_slot_utc": slot.expected_slot_utc,
        "execution_created_at_utc": _iso(created),
        "execution_started_at_utc": _iso(started),
        "actual_task_started_at_utc": _iso(task_started),
        "actual_task_start_delay_seconds": delay,
        "blocking_delay_seconds": BLOCKING_DELAY_SECONDS,
    }

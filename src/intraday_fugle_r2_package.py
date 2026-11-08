"""Offline R2 package and attested 09:35 admission preflight.

All trust pins are supplied by the independent reviewer. This module has no
credential, network, trigger, registry, or Production execution capability.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import re
from typing import Any, Mapping

from .intraday_fugle_live_consumption_fence import canonical_digest

TAIPEI = timezone(timedelta(hours=8))
WINDOW_START = "09:35:00"
WINDOW_END = "09:36:00"


class FugleR2PackageError(RuntimeError):
    pass


def require(condition: bool, reason: str) -> None:
    if not condition:
        raise FugleR2PackageError(reason)


def validate_r2_package(
    package: Mapping[str, Any],
    source_files: Mapping[str, bytes],
    *,
    expected_package_sha256: str,
    expected_source_sha: str,
    expected_workflow_sha256: str,
    expected_permit_id: str,
    expected_trigger_id: str,
    retired_trigger_ids: frozenset[str],
) -> dict[str, Any]:
    """Verify exact externally pinned material, never issue a permit or trigger."""
    require(isinstance(package, Mapping), "R2_PACKAGE_INVALID")
    require(canonical_digest(package) == expected_package_sha256, "R2_PACKAGE_PIN_MISMATCH")
    require(package.get("artifact") == "RATE_FUGLE_R2_OFFLINE_PACKAGE_V1"
            and package.get("scope") == "OFFLINE_CORRECTIVE_ONLY", "R2_PACKAGE_SCOPE_INVALID")
    require(re.fullmatch(r"[0-9a-f]{40}", expected_source_sha) is not None
            and package.get("source_sha") == expected_source_sha, "R2_SOURCE_PIN_MISMATCH")
    require(re.fullmatch(r"[0-9a-f]{64}", expected_workflow_sha256) is not None
            and package.get("workflow_sha256") == expected_workflow_sha256,
            "R2_WORKFLOW_PIN_MISMATCH")
    require(expected_permit_id.startswith("R2-") and package.get("permit_id") == expected_permit_id,
            "R2_PERMIT_ID_MISMATCH")
    require(expected_trigger_id.startswith("R2-")
            and package.get("trigger_id") == expected_trigger_id
            and expected_trigger_id not in retired_trigger_ids, "R2_TRIGGER_REUSE_OR_MISMATCH")
    require(package.get("trigger_created") is False
            and package.get("workflow_dispatch_allowed") is False
            and package.get("live_execution_allowed") is False, "R2_EXECUTION_FORBIDDEN")
    require(package.get("exchange_authority_gate") == "REQUIRED_UNCHANGED"
            and package.get("admission_proposal_status") == "PENDING_CONTROL_CENTER",
            "R2_ADMISSION_CONTRACT_CHANGE_FORBIDDEN")
    require(package.get("window_start_taipei") == WINDOW_START
            and package.get("window_end_taipei_exclusive") == WINDOW_END,
            "R2_WINDOW_POLICY_MISMATCH")
    inventory = package.get("source_files_sha256")
    require(isinstance(inventory, Mapping) and inventory and set(inventory) == set(source_files),
            "R2_SOURCE_INVENTORY_MISMATCH")
    for name, content in source_files.items():
        require(isinstance(name, str) and not name.startswith(("/", "\\"))
                and ":" not in name and "\\" not in name and ".." not in name.split("/"),
                "R2_SOURCE_PATH_INVALID")
        require(isinstance(content, bytes) and hashlib.sha256(content).hexdigest() == inventory[name],
                "R2_SOURCE_BYTES_MISMATCH")
    workflow_path = package.get("workflow_path")
    require(isinstance(workflow_path, str) and workflow_path.startswith(".github/workflows/")
            and inventory.get(workflow_path) == expected_workflow_sha256,
            "R2_WORKFLOW_BYTES_MISMATCH")
    return {
        "artifact": "RATE_FUGLE_R2_OFFLINE_PACKAGE_VERIFICATION_V1",
        "validation_status": "PASS",
        "source_sha": expected_source_sha,
        "workflow_sha256": expected_workflow_sha256,
        "permit_id": expected_permit_id,
        "trigger_id": expected_trigger_id,
        "live_execution_allowed": False,
        "credential_access": 0,
        "network_requests": 0,
        "production_credit": 0,
        "cer081_credit": 0,
    }


def _utc(value: str) -> datetime:
    try:
        stamp = datetime.fromisoformat(value)
        require(stamp.tzinfo is not None and stamp.utcoffset() == timedelta(0),
                "R2_CLOCK_TIMEZONE_INVALID")
        return stamp
    except (ValueError, TypeError) as exc:
        raise FugleR2PackageError("R2_CLOCK_TIMESTAMP_INVALID") from exc


def validate_r2_time(
    package: Mapping[str, Any],
    calendar: Mapping[str, Any],
    clock: Mapping[str, Any],
    *,
    expected_package_sha256: str,
    expected_calendar_sha256: str,
    expected_clock_sha256: str,
    trusted_clock_id: str,
    now_utc: datetime,
) -> dict[str, Any]:
    """Require a pinned trading calendar and fresh independent clock attestation.

    Proposed offline limits are a one-minute window, five-second attestation age,
    and at most one second of uncertainty. Control Center must approve live policy.
    """
    require(isinstance(package, Mapping) and canonical_digest(package) == expected_package_sha256,
            "R2_PACKAGE_PIN_MISMATCH")
    require(package.get("artifact") == "RATE_FUGLE_R2_OFFLINE_PACKAGE_V1"
            and package.get("scope") == "OFFLINE_CORRECTIVE_ONLY"
            and package.get("live_execution_allowed") is False, "R2_PACKAGE_SCOPE_INVALID")
    require(isinstance(package.get("source_sha"), str)
            and re.fullmatch(r"[0-9a-f]{40}", package["source_sha"]) is not None
            and isinstance(package.get("permit_id"), str) and package["permit_id"].startswith("R2-")
            and isinstance(package.get("trigger_id"), str) and package["trigger_id"].startswith("R2-"),
            "R2_CLOCK_PACKAGE_BINDING_INVALID")
    require(isinstance(calendar, Mapping) and canonical_digest(calendar) == expected_calendar_sha256,
            "R2_CALENDAR_PIN_MISMATCH")
    require(calendar.get("status") == "VERIFIED"
            and calendar.get("markets") == ["TWSE", "TPEX"], "R2_CALENDAR_UNTRUSTED")
    day = package.get("trading_date")
    require(isinstance(day, str) and day in calendar.get("trading_dates", []),
            "R2_NOT_TRADING_DAY")
    require(isinstance(clock, Mapping) and canonical_digest(clock) == expected_clock_sha256,
            "R2_CLOCK_PIN_MISMATCH")
    require(isinstance(trusted_clock_id, str) and bool(trusted_clock_id)
            and clock.get("authority_id") == trusted_clock_id
            and clock.get("synchronization_status") == "VERIFIED", "R2_CLOCK_UNTRUSTED")
    require(clock.get("source_sha") == package.get("source_sha")
            and clock.get("permit_id") == package.get("permit_id")
            and clock.get("trigger_id") == package.get("trigger_id"), "R2_CLOCK_BINDING_MISMATCH")
    uncertainty = clock.get("uncertainty_ms")
    require(type(uncertainty) is int and 0 <= uncertainty <= 1000, "R2_CLOCK_UNCERTAINTY_INVALID")
    sampled = _utc(clock.get("sampled_at_utc"))
    require(isinstance(now_utc, datetime) and now_utc.tzinfo is not None
            and now_utc.utcoffset() == timedelta(0), "R2_NOW_TIMEZONE_INVALID")
    require(0 <= (now_utc - sampled).total_seconds() <= 5, "R2_CLOCK_STALE_OR_FUTURE")
    local = now_utc.astimezone(TAIPEI)
    require(local.date().isoformat() == day, "R2_TRADING_DATE_MISMATCH")
    require(package.get("window_start_taipei") == WINDOW_START
            and package.get("window_end_taipei_exclusive") == WINDOW_END, "R2_WINDOW_POLICY_MISMATCH")
    start = datetime.fromisoformat(day + "T" + WINDOW_START).replace(tzinfo=TAIPEI)
    end = datetime.fromisoformat(day + "T" + WINDOW_END).replace(tzinfo=TAIPEI)
    margin = timedelta(milliseconds=uncertainty)
    require(start <= local - margin and local + margin < end, "R2_OUTSIDE_0935_WINDOW")
    return {
        "validation_status": "PASS",
        "package_sha256": expected_package_sha256,
        "source_sha": package["source_sha"],
        "permit_id": package["permit_id"],
        "trigger_id": package["trigger_id"],
        "trading_date": day,
        "observed_at_utc": now_utc.isoformat(),
        "clock_attestation_sha256": expected_clock_sha256,
        "calendar_sha256": expected_calendar_sha256,
        "live_execution_allowed": False,
        "credential_access": 0,
        "network_requests": 0,
    }

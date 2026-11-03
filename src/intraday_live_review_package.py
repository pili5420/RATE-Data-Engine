"""Build a deterministic evidence package for independent intraday live review.

This is packaging only. It does not decide review PASS/FAIL, does not create an
external expected hash, and does not activate a provider.
"""
from __future__ import annotations

from copy import deepcopy
import re
from typing import Any, Mapping

from .intraday_live_qualification_review import canonical_digest

HEX40 = re.compile(r"^[0-9a-f]{40}$")
ALLOWED_CADENCES = {"09:30", "12:00"}


class LiveReviewPackageError(RuntimeError):
    pass


def require(condition: bool, reason: str) -> None:
    if not condition:
        raise LiveReviewPackageError(reason)


def _sha40(value: Any, reason: str) -> str:
    text = str(value or "").lower()
    require(bool(HEX40.fullmatch(text)), reason)
    return text


def _positive_int(value: Any, reason: str) -> int:
    require(isinstance(value, int) and not isinstance(value, bool) and value > 0, reason)
    return value


def build_live_review_package(
    result: Mapping[str, Any],
    *,
    engineering_source_sha: str,
    trigger_commit_sha: str,
    workflow_run_id: int,
    workflow_job_id: int,
    provider_name: str,
    trading_date: str,
    cadence: str,
    workflow_attempt: int = 1,
    rerun_count: int = 0,
    job_retry_count: int = 0,
    single_use_consumed: bool = True,
    secret_scan_status: str,
) -> dict[str, Any]:
    engineering = _sha40(engineering_source_sha, "LIVE_PACKAGE_ENGINEERING_SHA_INVALID")
    trigger = _sha40(trigger_commit_sha, "LIVE_PACKAGE_TRIGGER_SHA_INVALID")
    run_id = _positive_int(workflow_run_id, "LIVE_PACKAGE_RUN_ID_INVALID")
    job_id = _positive_int(workflow_job_id, "LIVE_PACKAGE_JOB_ID_INVALID")

    require(isinstance(provider_name, str) and provider_name.strip(),
            "LIVE_PACKAGE_PROVIDER_INVALID")
    require(isinstance(trading_date, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", trading_date),
            "LIVE_PACKAGE_TRADING_DATE_INVALID")
    require(cadence in ALLOWED_CADENCES, "LIVE_PACKAGE_CADENCE_INVALID")
    require(workflow_attempt == 1, "LIVE_PACKAGE_WORKFLOW_ATTEMPT_INVALID")
    require(rerun_count == 0 and job_retry_count == 0, "LIVE_PACKAGE_RETRY_FORBIDDEN")
    require(single_use_consumed is True, "LIVE_PACKAGE_SINGLE_USE_NOT_CONSUMED")
    require(secret_scan_status == "PASS_NO_SECRET_EXPOSURE",
            "LIVE_PACKAGE_SECRET_SCAN_NOT_PASS")

    require(isinstance(result, Mapping), "LIVE_PACKAGE_RESULT_INVALID")
    require(result.get("artifact") == "RATE_FUGLE_FREE_INTRADAY_DIAGNOSTIC_RESULT_V1",
            "LIVE_PACKAGE_RESULT_ARTIFACT_INVALID")
    require(result.get("provider") == provider_name, "LIVE_PACKAGE_RESULT_PROVIDER_MISMATCH")
    require(result.get("trading_date") == trading_date and result.get("cadence") == cadence,
            "LIVE_PACKAGE_RESULT_SCOPE_MISMATCH")

    copied = deepcopy(dict(result))
    result_sha = canonical_digest(copied)
    return {
        "artifact": "RATE_INTRADAY_SINGLE_LIVE_QUALIFICATION_REVIEW_PACKAGE_V1",
        "review_scope": "SINGLE_LIVE_QUALIFICATION",
        "single_use_consumed": True,
        "workflow_attempt": 1,
        "rerun_count": 0,
        "job_retry_count": 0,
        "engineering_source_sha": engineering,
        "trigger_commit_sha": trigger,
        "workflow_run_id": run_id,
        "workflow_job_id": job_id,
        "provider_name": provider_name,
        "trading_date": trading_date,
        "cadence": cadence,
        "result_sha256": result_sha,
        "result": copied,
        "secret_exposure": {
            "api_key_in_result": False,
            "api_key_in_logs": False,
            "raw_secret_persisted": False,
        },
        "live_provider_requests": result.get("network_requests"),
        "fallback_used": result.get("fallback_used"),
        "production_credit": 0,
        "cer081_credit": 0,
        "package_builder_disposition": "NOT_A_REVIEW_DECISION",
    }

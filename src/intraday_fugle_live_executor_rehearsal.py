"""Offline rehearsal for the future Fugle single-live executor.

Builds an exact execution plan from a validated authorization without reading
credentials or performing network I/O.
"""
from __future__ import annotations

import re
from typing import Any, Mapping

HEX40 = re.compile(r"^[0-9a-f]{40}$")
HEX64 = re.compile(r"^[0-9a-f]{64}$")


class FugleLiveExecutorRehearsalError(RuntimeError):
    pass


def require(condition: bool, reason: str) -> None:
    if not condition:
        raise FugleLiveExecutorRehearsalError(reason)


def _hex40(value: Any, reason: str) -> str:
    text=str(value or "").lower()
    require(bool(HEX40.fullmatch(text)), reason)
    return text


def _hex64(value: Any, reason: str) -> str:
    text=str(value or "").lower()
    require(bool(HEX64.fullmatch(text)), reason)
    return text


def build_fugle_live_executor_rehearsal(
    authorization_review: Mapping[str, Any],
    *,
    expected_main_sha: str,
    expected_authorization_sha256: str,
    trading_date: str,
    output_name: str,
) -> dict[str, Any]:
    main=_hex40(expected_main_sha, "FUGLE_EXEC_REHEARSAL_MAIN_SHA_INVALID")
    auth_hash=_hex64(expected_authorization_sha256, "FUGLE_EXEC_REHEARSAL_AUTH_HASH_INVALID")

    require(isinstance(authorization_review, Mapping),
            "FUGLE_EXEC_REHEARSAL_AUTH_REVIEW_INVALID")
    require(
        authorization_review.get("artifact")
        == "RATE_FUGLE_SINGLE_LIVE_QUALIFICATION_AUTHORIZATION_QUALIFICATION_V1"
        and authorization_review.get("validation_status") == "PASS",
        "FUGLE_EXEC_REHEARSAL_AUTH_REVIEW_NOT_PASS",
    )
    require(authorization_review.get("authorization_sha256") == auth_hash,
            "FUGLE_EXEC_REHEARSAL_AUTH_HASH_MISMATCH")
    require(authorization_review.get("current_main_sha") == main,
            "FUGLE_EXEC_REHEARSAL_MAIN_SHA_MISMATCH")
    require(authorization_review.get("provider") == "Fugle",
            "FUGLE_EXEC_REHEARSAL_PROVIDER_INVALID")
    require(authorization_review.get("request_budget") == 30,
            "FUGLE_EXEC_REHEARSAL_REQUEST_BUDGET_INVALID")
    require(authorization_review.get("single_use") is True
            and authorization_review.get("execution_consumed") is False,
            "FUGLE_EXEC_REHEARSAL_SINGLE_USE_INVALID")
    require(authorization_review.get("automatic_retry_allowed") is False
            and authorization_review.get("fallback_allowed") is False
            and authorization_review.get("redirect_allowed") is False,
            "FUGLE_EXEC_REHEARSAL_NETWORK_BOUNDARY_INVALID")
    require(authorization_review.get("credential_secret_name") == "FUGLE_API_KEY",
            "FUGLE_EXEC_REHEARSAL_SECRET_NAME_INVALID")
    require(authorization_review.get("qualification_execution_allowed_by_validator") is False
            and authorization_review.get("qualification_execution_performed") is False
            and authorization_review.get("live_requests_performed") == 0,
            "FUGLE_EXEC_REHEARSAL_PREMATURE_EXECUTION")

    require(isinstance(trading_date, str)
            and bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}", trading_date)),
            "FUGLE_EXEC_REHEARSAL_TRADING_DATE_INVALID")
    require(isinstance(output_name, str) and output_name.endswith(".json")
            and "/" not in output_name and "\\" not in output_name
            and output_name not in {".json", "..json"},
            "FUGLE_EXEC_REHEARSAL_OUTPUT_NAME_INVALID")

    cadence=authorization_review.get("cadence")
    require(cadence in {"09:30","12:00"}, "FUGLE_EXEC_REHEARSAL_CADENCE_INVALID")

    command=[
        "python","-I","scripts/run_fugle_intraday_qualification.py",
        "--trading-date",trading_date,
        "--cadence",cadence,
        "--output-name",output_name,
    ]

    return {
        "artifact":"RATE_FUGLE_SINGLE_LIVE_EXECUTOR_REHEARSAL_V1",
        "validation_status":"PASS",
        "rehearsal_disposition":"READY_FOR_SEPARATE_AUTHORIZED_EXECUTOR_IMPLEMENTATION",
        "current_main_sha":main,
        "authorization_sha256":auth_hash,
        "provider":"Fugle",
        "trading_date":trading_date,
        "cadence":cadence,
        "request_budget":30,
        "command":command,
        "consumption_order":[
            "VALIDATE_AUTHORIZATION",
            "CREATE_DURABLE_SINGLE_USE_CONSUMPTION_MARKER",
            "VERIFY_CONSUMPTION_MARKER_READBACK",
            "READ_FUGLE_API_KEY",
            "EXECUTE_EXACT_30_REQUEST_QUALIFICATION",
            "EXCLUSIVE_CREATE_RESULT",
            "BUILD_INDEPENDENT_LIVE_REVIEW_PACKAGE"
        ],
        "consumption_marker_required_before_credential_access":True,
        "consumption_marker_required_before_first_network_request":True,
        "automatic_retry_allowed":False,
        "fallback_allowed":False,
        "redirect_allowed":False,
        "credential_secret_name":"FUGLE_API_KEY",
        "credential_value_embedded":False,
        "network_requests_by_rehearsal":0,
        "credential_access_by_rehearsal":0,
        "files_written_by_rehearsal":0,
        "authorization_consumed_by_rehearsal":False,
        "production_activation_allowed":False,
        "external_dependency_resolved":False,
        "production_credit":0,
        "cer081_credit":0,
        "next_gate":"SEPARATE_AUTHORIZED_FUGLE_SINGLE_LIVE_EXECUTOR"
    }

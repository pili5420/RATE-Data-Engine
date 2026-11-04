"""Pure validator for one fresh Fugle single-live qualification authorization."""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Mapping

HEX40 = re.compile(r"^[0-9a-f]{40}$")
HEX64 = re.compile(r"^[0-9a-f]{64}$")
ALLOWED_CADENCES = {"09:30", "12:00"}


class FugleSingleLiveAuthorizationError(RuntimeError):
    pass


def require(condition: bool, reason: str) -> None:
    if not condition:
        raise FugleSingleLiveAuthorizationError(reason)


def canonical_digest(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _hex40(value: Any, reason: str) -> str:
    text = str(value or "").lower()
    require(bool(HEX40.fullmatch(text)), reason)
    return text


def _hex64(value: Any, reason: str) -> str:
    text = str(value or "").lower()
    require(bool(HEX64.fullmatch(text)), reason)
    return text


def validate_fugle_single_live_authorization(
    authorization: Mapping[str, Any],
    readiness: Mapping[str, Any],
    *,
    expected_authorization_sha256: str,
    expected_readiness_sha256: str,
    expected_main_sha: str,
    expected_control_center_decision_id: str,
) -> dict[str, Any]:
    auth_hash = _hex64(expected_authorization_sha256, "FUGLE_AUTH_EXPECTED_AUTH_HASH_INVALID")
    readiness_hash = _hex64(expected_readiness_sha256, "FUGLE_AUTH_EXPECTED_READINESS_HASH_INVALID")
    main_sha = _hex40(expected_main_sha, "FUGLE_AUTH_EXPECTED_MAIN_SHA_INVALID")
    require(isinstance(expected_control_center_decision_id, str)
            and expected_control_center_decision_id.strip(),
            "FUGLE_AUTH_EXPECTED_DECISION_ID_INVALID")

    require(isinstance(readiness, Mapping), "FUGLE_AUTH_READINESS_INVALID")
    require(canonical_digest(readiness) == readiness_hash,
            "FUGLE_AUTH_READINESS_HASH_MISMATCH")
    require(
        readiness.get("artifact") == "RATE_INTRADAY_NEW_SINGLE_LIVE_QUALIFICATION_READINESS_V1"
        and readiness.get("validation_status") == "PASS"
        and readiness.get("readiness_disposition")
        == "READY_FOR_CONTROL_CENTER_NEW_SINGLE_LIVE_AUTHORIZATION",
        "FUGLE_AUTH_READINESS_NOT_PASS",
    )
    require(readiness.get("main_sha") == main_sha,
            "FUGLE_AUTH_READINESS_MAIN_MISMATCH")
    require(readiness.get("provider_name") == "Fugle",
            "FUGLE_AUTH_READINESS_PROVIDER_MISMATCH")
    require(readiness.get("fresh_control_center_authorization_required") is True,
            "FUGLE_AUTH_FRESH_AUTHORIZATION_REQUIRED")
    require(readiness.get("previous_single_use_permit_reusable") is False,
            "FUGLE_AUTH_OLD_PERMIT_REUSE_FORBIDDEN")
    require(readiness.get("live_requests_authorized_by_this_gate") == 0,
            "FUGLE_AUTH_READINESS_PREMATURE_EXECUTION")
    require(readiness.get("production_activation_allowed") is False
            and readiness.get("external_dependency_resolved") is False
            and readiness.get("production_credit") == 0
            and readiness.get("cer081_credit") == 0,
            "FUGLE_AUTH_READINESS_PREMATURE_PRODUCTION_STATE")

    require(isinstance(authorization, Mapping), "FUGLE_AUTHORIZATION_INVALID")
    require(canonical_digest(authorization) == auth_hash,
            "FUGLE_AUTHORIZATION_HASH_MISMATCH")
    require(
        authorization.get("artifact") == "RATE_FUGLE_SINGLE_LIVE_QUALIFICATION_AUTHORIZATION_V1"
        and authorization.get("status") == "FUGLE_SINGLE_LIVE_QUALIFICATION_AUTHORIZED",
        "FUGLE_AUTHORIZATION_STATUS_INVALID",
    )
    require(authorization.get("control_center_decision_id") == expected_control_center_decision_id,
            "FUGLE_AUTHORIZATION_DECISION_ID_MISMATCH")
    require(authorization.get("current_main_sha") == main_sha,
            "FUGLE_AUTHORIZATION_MAIN_SHA_MISMATCH")
    require(authorization.get("readiness_sha256") == readiness_hash,
            "FUGLE_AUTHORIZATION_READINESS_BINDING_MISMATCH")
    require(authorization.get("provider") == "Fugle",
            "FUGLE_AUTHORIZATION_PROVIDER_INVALID")
    require(authorization.get("cadence") in ALLOWED_CADENCES,
            "FUGLE_AUTHORIZATION_CADENCE_INVALID")
    require(authorization.get("request_budget") == 30,
            "FUGLE_AUTHORIZATION_REQUEST_BUDGET_INVALID")
    require(authorization.get("single_use") is True
            and authorization.get("execution_consumed") is False,
            "FUGLE_AUTHORIZATION_SINGLE_USE_BOUNDARY_INVALID")
    require(authorization.get("automatic_retry_allowed") is False
            and authorization.get("fallback_allowed") is False
            and authorization.get("redirect_allowed") is False,
            "FUGLE_AUTHORIZATION_NETWORK_BOUNDARY_INVALID")
    require(authorization.get("credential_store") == "GITHUB_ACTIONS_SECRET"
            and authorization.get("credential_secret_name") == "FUGLE_API_KEY"
            and authorization.get("credential_value_embedded") is False,
            "FUGLE_AUTHORIZATION_CREDENTIAL_BOUNDARY_INVALID")
    require(authorization.get("qualification_execution_performed") is False
            and authorization.get("live_requests_performed") == 0
            and authorization.get("credential_access") == 0
            and authorization.get("production_credit") == 0
            and authorization.get("cer081_credit") == 0,
            "FUGLE_AUTHORIZATION_PREMATURE_EXECUTION_OR_CREDIT")

    return {
        "artifact": "RATE_FUGLE_SINGLE_LIVE_QUALIFICATION_AUTHORIZATION_QUALIFICATION_V1",
        "validation_status": "PASS",
        "authorization_sha256": auth_hash,
        "readiness_sha256": readiness_hash,
        "current_main_sha": main_sha,
        "control_center_decision_id": expected_control_center_decision_id,
        "provider": "Fugle",
        "cadence": authorization["cadence"],
        "request_budget": 30,
        "single_use": True,
        "execution_consumed": False,
        "automatic_retry_allowed": False,
        "fallback_allowed": False,
        "redirect_allowed": False,
        "credential_store": "GITHUB_ACTIONS_SECRET",
        "credential_secret_name": "FUGLE_API_KEY",
        "qualification_execution_allowed_by_validator": False,
        "qualification_execution_performed": False,
        "live_requests_performed": 0,
        "credential_access": 0,
        "production_activation_allowed": False,
        "external_dependency_resolved": False,
        "production_credit": 0,
        "cer081_credit": 0,
        "next_gate": "SEPARATE_FUGLE_SINGLE_LIVE_QUALIFICATION_EXECUTOR",
    }

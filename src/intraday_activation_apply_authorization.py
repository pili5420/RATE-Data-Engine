"""Validate one explicit Control Center authorization for a future intraday activation apply.

This gate validates authorization metadata only. It does not materialize or apply
candidate files, does not mutate repository state, and does not resolve Production
dependencies.
"""
from __future__ import annotations

import re
from typing import Any, Mapping

from .intraday_activation_candidate_review import canonical_digest
from .intraday_activation_delta_plan import NEW_RUNTIME_FILES
from .intraday_activation_readiness import ALLOWED_EXISTING_MUTATION_PATHS

HEX40 = re.compile(r"^[0-9a-f]{40}$")
HEX64 = re.compile(r"^[0-9a-f]{64}$")
EXPECTED_PATHS = tuple(sorted(
    set(ALLOWED_EXISTING_MUTATION_PATHS) | set(NEW_RUNTIME_FILES)
))


class ActivationApplyAuthorizationError(RuntimeError):
    pass


def require(condition: bool, reason: str) -> None:
    if not condition:
        raise ActivationApplyAuthorizationError(reason)


def _sha40(value: Any, reason: str) -> str:
    text = str(value or "").lower()
    require(bool(HEX40.fullmatch(text)), reason)
    return text


def _sha64(value: Any, reason: str) -> str:
    text = str(value or "").lower()
    require(bool(HEX64.fullmatch(text)), reason)
    return text


def validate_activation_apply_authorization(
    authorization: Mapping[str, Any],
    final_main_readiness: Mapping[str, Any],
    *,
    expected_authorization_sha256: str,
    expected_final_main_readiness_sha256: str,
    expected_current_main_sha: str,
    expected_candidate_manifest_sha256: str,
    expected_provider_name: str,
    expected_decision_id: str,
) -> dict[str, Any]:
    authorization_hash = _sha64(
        expected_authorization_sha256,
        "ACTIVATION_APPLY_EXPECTED_AUTHORIZATION_HASH_INVALID",
    )
    readiness_hash = _sha64(
        expected_final_main_readiness_sha256,
        "ACTIVATION_APPLY_EXPECTED_READINESS_HASH_INVALID",
    )
    current_main = _sha40(
        expected_current_main_sha,
        "ACTIVATION_APPLY_EXPECTED_MAIN_SHA_INVALID",
    )
    manifest_hash = _sha64(
        expected_candidate_manifest_sha256,
        "ACTIVATION_APPLY_EXPECTED_CANDIDATE_MANIFEST_HASH_INVALID",
    )
    require(
        isinstance(expected_provider_name, str) and expected_provider_name.strip(),
        "ACTIVATION_APPLY_EXPECTED_PROVIDER_INVALID",
    )
    require(
        isinstance(expected_decision_id, str) and expected_decision_id.strip(),
        "ACTIVATION_APPLY_EXPECTED_DECISION_ID_INVALID",
    )

    require(
        isinstance(final_main_readiness, Mapping),
        "ACTIVATION_APPLY_READINESS_INVALID",
    )
    require(
        canonical_digest(final_main_readiness) == readiness_hash,
        "ACTIVATION_APPLY_READINESS_HASH_MISMATCH",
    )
    require(
        final_main_readiness.get("artifact")
        == "RATE_INTRADAY_FINAL_MAIN_ACTIVATION_APPLY_READINESS_V1"
        and final_main_readiness.get("validation_status") == "PASS"
        and final_main_readiness.get("review_disposition")
        == "READY_FOR_CONTROL_CENTER_ACTIVATION_APPLY_AUTHORIZATION",
        "ACTIVATION_APPLY_READINESS_NOT_PASS",
    )
    require(
        final_main_readiness.get("current_main_sha") == current_main,
        "ACTIVATION_APPLY_READINESS_MAIN_MISMATCH",
    )
    require(
        final_main_readiness.get("rebased_candidate_manifest_sha256") == manifest_hash,
        "ACTIVATION_APPLY_READINESS_MANIFEST_MISMATCH",
    )
    require(
        final_main_readiness.get("provider_name") == expected_provider_name,
        "ACTIVATION_APPLY_READINESS_PROVIDER_MISMATCH",
    )
    require(
        final_main_readiness.get("provider_accepted") is True
        and final_main_readiness.get("apply_allowed") is False
        and final_main_readiness.get("activation_execution_allowed") is False
        and final_main_readiness.get("external_dependency_resolved") is False
        and final_main_readiness.get("registry_activation_allowed") is False
        and final_main_readiness.get("production_credit") == 0
        and final_main_readiness.get("cer081_credit") == 0,
        "ACTIVATION_APPLY_READINESS_PREMATURE_STATE",
    )

    require(
        isinstance(authorization, Mapping),
        "ACTIVATION_APPLY_AUTHORIZATION_INVALID",
    )
    require(
        canonical_digest(authorization) == authorization_hash,
        "ACTIVATION_APPLY_AUTHORIZATION_HASH_MISMATCH",
    )
    require(
        authorization.get("artifact")
        == "RATE_INTRADAY_ACTIVATION_APPLY_AUTHORIZATION_V1",
        "ACTIVATION_APPLY_AUTHORIZATION_ARTIFACT_INVALID",
    )
    require(
        authorization.get("status") == "ACTIVATION_APPLY_AUTHORIZED",
        "ACTIVATION_APPLY_AUTHORIZATION_STATUS_INVALID",
    )
    require(
        authorization.get("control_center_decision_id") == expected_decision_id,
        "ACTIVATION_APPLY_DECISION_ID_MISMATCH",
    )
    require(
        authorization.get("current_main_sha") == current_main,
        "ACTIVATION_APPLY_MAIN_SHA_MISMATCH",
    )
    require(
        authorization.get("candidate_manifest_sha256") == manifest_hash,
        "ACTIVATION_APPLY_CANDIDATE_MANIFEST_MISMATCH",
    )
    require(
        authorization.get("final_main_readiness_sha256") == readiness_hash,
        "ACTIVATION_APPLY_READINESS_BINDING_MISMATCH",
    )
    require(
        authorization.get("provider_name") == expected_provider_name,
        "ACTIVATION_APPLY_PROVIDER_MISMATCH",
    )
    require(
        authorization.get("single_use") is True,
        "ACTIVATION_APPLY_SINGLE_USE_REQUIRED",
    )
    require(
        authorization.get("automatic_retry_allowed") is False,
        "ACTIVATION_APPLY_AUTORETRY_FORBIDDEN",
    )
    require(
        authorization.get("fallback_allowed") is False,
        "ACTIVATION_APPLY_FALLBACK_FORBIDDEN",
    )

    paths = authorization.get("allowed_paths")
    require(
        isinstance(paths, list)
        and len(paths) == len(EXPECTED_PATHS)
        and set(paths) == set(EXPECTED_PATHS),
        "ACTIVATION_APPLY_PATH_ALLOWLIST_INVALID",
    )
    require(
        authorization.get("allowed_operations")
        == ["CREATE_OR_REPLACE_EXACT_CANDIDATE_FILES"],
        "ACTIVATION_APPLY_OPERATION_SCOPE_INVALID",
    )
    require(
        authorization.get("credential_value_embedded") is False,
        "ACTIVATION_APPLY_SECRET_VALUE_FORBIDDEN",
    )
    require(
        authorization.get("live_provider_requests_allowed") == 0,
        "ACTIVATION_APPLY_LIVE_REQUEST_FORBIDDEN",
    )
    require(
        authorization.get("production_credit_before_apply") == 0
        and authorization.get("cer081_credit_before_apply") == 0,
        "ACTIVATION_APPLY_PREMATURE_CREDIT",
    )

    return {
        "artifact": "RATE_INTRADAY_ACTIVATION_APPLY_AUTHORIZATION_QUALIFICATION_V1",
        "validation_status": "PASS",
        "control_center_decision_id": expected_decision_id,
        "authorization_sha256": authorization_hash,
        "final_main_readiness_sha256": readiness_hash,
        "current_main_sha": current_main,
        "candidate_manifest_sha256": manifest_hash,
        "provider_name": expected_provider_name,
        "single_use": True,
        "automatic_retry_allowed": False,
        "fallback_allowed": False,
        "allowed_paths": list(EXPECTED_PATHS),
        "authorization_valid": True,
        "apply_executed": False,
        "activation_execution_allowed_by_this_validator": False,
        "external_dependency_resolved": False,
        "registry_activation_allowed": False,
        "repository_writes": 0,
        "live_provider_requests": 0,
        "production_credit": 0,
        "cer081_credit": 0,
        "next_gate": "SEPARATE_SINGLE_USE_ACTIVATION_APPLY_EXECUTOR",
    }

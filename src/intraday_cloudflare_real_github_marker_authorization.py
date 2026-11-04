"""Pure authorization qualification for one real GitHub Cloudflare-consumption marker creation.

No GitHub request is performed. The gate binds one exact Cloudflare qualification
authorization to one exact marker ref and current main, with a minimal GET/POST/GET
operation budget.
"""
from __future__ import annotations

import re
from typing import Any, Mapping

from .intraday_activation_candidate_review import canonical_digest
from .intraday_cloudflare_github_marker_adapter import marker_ref

HEX40 = re.compile(r"^[0-9a-f]{40}$")
HEX64 = re.compile(r"^[0-9a-f]{64}$")
ALLOWED_OPERATIONS = (
    "GET_MARKER_PREFLIGHT",
    "CREATE_MARKER_REF",
    "GET_MARKER_READBACK",
)


class MarkerCreationAuthorizationError(RuntimeError):
    pass


def require(condition: bool, reason: str) -> None:
    if not condition:
        raise MarkerCreationAuthorizationError(reason)


def _sha40(value: Any, reason: str) -> str:
    text = str(value or "").lower()
    require(bool(HEX40.fullmatch(text)), reason)
    return text


def _sha64(value: Any, reason: str) -> str:
    text = str(value or "").lower()
    require(bool(HEX64.fullmatch(text)), reason)
    return text


def validate_marker_creation_authorization(
    authorization: Mapping[str, Any],
    cloudflare_qualification_authorization: Mapping[str, Any],
    *,
    expected_authorization_sha256: str,
    expected_cloudflare_authorization_sha256: str,
    expected_current_main_sha: str,
) -> dict[str, Any]:
    auth_hash = _sha64(
        expected_authorization_sha256,
        "GH_MARKER_AUTHZ_EXPECTED_AUTHORIZATION_HASH_INVALID",
    )
    cloudflare_hash = _sha64(
        expected_cloudflare_authorization_sha256,
        "GH_MARKER_AUTHZ_EXPECTED_CLOUDFLARE_AUTH_HASH_INVALID",
    )
    main = _sha40(
        expected_current_main_sha,
        "GH_MARKER_AUTHZ_EXPECTED_MAIN_INVALID",
    )

    require(
        isinstance(cloudflare_qualification_authorization, Mapping),
        "GH_MARKER_AUTHZ_CLOUDFLARE_AUTH_INVALID",
    )
    require(
        canonical_digest(cloudflare_qualification_authorization) == cloudflare_hash,
        "GH_MARKER_AUTHZ_CLOUDFLARE_AUTH_HASH_MISMATCH",
    )
    require(
        cloudflare_qualification_authorization.get("artifact")
        == "RATE_CLOUDFLARE_D1_REAL_PROVIDER_QUALIFICATION_AUTHORIZATION_QUALIFICATION_V1"
        and cloudflare_qualification_authorization.get("validation_status") == "PASS",
        "GH_MARKER_AUTHZ_CLOUDFLARE_AUTH_NOT_PASS",
    )
    require(
        cloudflare_qualification_authorization.get("current_main_sha") == main,
        "GH_MARKER_AUTHZ_CLOUDFLARE_MAIN_MISMATCH",
    )
    require(
        cloudflare_qualification_authorization.get("single_use") is True
        and cloudflare_qualification_authorization.get("execution_consumed") is False
        and cloudflare_qualification_authorization.get("automatic_retry_allowed") is False
        and cloudflare_qualification_authorization.get("fallback_allowed") is False
        and cloudflare_qualification_authorization.get("real_cloudflare_requests") == 0
        and cloudflare_qualification_authorization.get("provider_qualified") is False,
        "GH_MARKER_AUTHZ_CLOUDFLARE_BOUNDARY_INVALID",
    )

    expected_ref = marker_ref(cloudflare_qualification_authorization["authorization_sha256"])

    require(isinstance(authorization, Mapping), "GH_MARKER_AUTHZ_INVALID")
    require(
        canonical_digest(authorization) == auth_hash,
        "GH_MARKER_AUTHZ_HASH_MISMATCH",
    )
    require(
        authorization.get("artifact")
        == "RATE_CLOUDFLARE_REAL_GITHUB_MARKER_CREATION_AUTHORIZATION_V1"
        and authorization.get("status") == "REAL_GITHUB_MARKER_CREATION_AUTHORIZED",
        "GH_MARKER_AUTHZ_STATUS_INVALID",
    )
    require(
        authorization.get("cloudflare_authorization_qualification_sha256") == cloudflare_hash,
        "GH_MARKER_AUTHZ_CLOUDFLARE_BINDING_MISMATCH",
    )
    require(
        authorization.get("current_main_sha") == main
        and authorization.get("marker_target_sha") == main,
        "GH_MARKER_AUTHZ_MAIN_BINDING_MISMATCH",
    )
    require(
        authorization.get("marker_ref") == expected_ref,
        "GH_MARKER_AUTHZ_REF_BINDING_MISMATCH",
    )
    require(
        authorization.get("single_use") is True
        and authorization.get("marker_creation_consumed") is False
        and authorization.get("automatic_retry_allowed") is False
        and authorization.get("fallback_allowed") is False,
        "GH_MARKER_AUTHZ_SINGLE_USE_BOUNDARY_INVALID",
    )
    require(
        authorization.get("allowed_operations") == list(ALLOWED_OPERATIONS),
        "GH_MARKER_AUTHZ_OPERATIONS_INVALID",
    )
    require(
        authorization.get("create_count") == 1
        and authorization.get("update_count") == 0
        and authorization.get("delete_count") == 0
        and authorization.get("readback_required") is True,
        "GH_MARKER_AUTHZ_BUDGET_INVALID",
    )
    require(
        authorization.get("main_ref_update_allowed") is False
        and authorization.get("branch_ref_create_allowed") is False
        and authorization.get("pull_request_creation_allowed") is False
        and authorization.get("merge_allowed") is False
        and authorization.get("cloudflare_requests_allowed_before_marker") == 0,
        "GH_MARKER_AUTHZ_FORBIDDEN_ACTION_BOUNDARY_INVALID",
    )

    return {
        "artifact": "RATE_CLOUDFLARE_REAL_GITHUB_MARKER_CREATION_AUTHORIZATION_QUALIFICATION_V1",
        "validation_status": "PASS",
        "authorization_sha256": auth_hash,
        "cloudflare_authorization_qualification_sha256": cloudflare_hash,
        "current_main_sha": main,
        "marker_ref": expected_ref,
        "marker_target_sha": main,
        "single_use": True,
        "marker_creation_consumed": False,
        "automatic_retry_allowed": False,
        "fallback_allowed": False,
        "allowed_operations": list(ALLOWED_OPERATIONS),
        "create_count": 1,
        "update_count": 0,
        "delete_count": 0,
        "readback_required": True,
        "execution_performed": False,
        "real_github_requests": 0,
        "real_git_ref_created": False,
        "real_cloudflare_requests": 0,
        "production_credit": 0,
        "cer081_credit": 0,
        "next_gate": "SEPARATE_REAL_GITHUB_MARKER_EXECUTOR",
    }

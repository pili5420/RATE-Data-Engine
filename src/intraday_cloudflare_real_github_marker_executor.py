"""Executor logic for one Cloudflare qualification consumption marker.

CI accepts only the synthetic GitHub transport. The executor validates one exact
#144 authorization qualification, then delegates the bounded GET/POST/GET sequence
to the #143 marker adapter.
"""
from __future__ import annotations

from typing import Any, Mapping

from .intraday_activation_candidate_review import canonical_digest
from .intraday_cloudflare_github_marker_adapter import (
    SyntheticGitHubRefTransport,
    marker_ref,
    qualify_marker_adapter,
)


class MarkerExecutorError(RuntimeError):
    pass


def require(condition: bool, reason: str) -> None:
    if not condition:
        raise MarkerExecutorError(reason)


def execute_marker(
    authorization_qualification: Mapping[str, Any],
    transport: SyntheticGitHubRefTransport,
    *,
    expected_authorization_qualification_sha256: str,
) -> dict[str, Any]:
    require(
        canonical_digest(authorization_qualification)
        == expected_authorization_qualification_sha256,
        "GH_MARKER_EXEC_AUTH_QUAL_HASH_MISMATCH",
    )
    require(
        authorization_qualification.get("artifact")
        == "RATE_CLOUDFLARE_REAL_GITHUB_MARKER_CREATION_AUTHORIZATION_QUALIFICATION_V1"
        and authorization_qualification.get("validation_status") == "PASS",
        "GH_MARKER_EXEC_AUTH_QUAL_NOT_PASS",
    )
    require(
        authorization_qualification.get("single_use") is True
        and authorization_qualification.get("marker_creation_consumed") is False
        and authorization_qualification.get("automatic_retry_allowed") is False
        and authorization_qualification.get("fallback_allowed") is False,
        "GH_MARKER_EXEC_SINGLE_USE_BOUNDARY_INVALID",
    )
    require(
        authorization_qualification.get("allowed_operations")
        == ["GET_MARKER_PREFLIGHT","CREATE_MARKER_REF","GET_MARKER_READBACK"]
        and authorization_qualification.get("create_count") == 1
        and authorization_qualification.get("update_count") == 0
        and authorization_qualification.get("delete_count") == 0
        and authorization_qualification.get("readback_required") is True,
        "GH_MARKER_EXEC_OPERATION_BUDGET_INVALID",
    )
    require(
        authorization_qualification.get("execution_performed") is False
        and authorization_qualification.get("real_github_requests") == 0
        and authorization_qualification.get("real_git_ref_created") is False
        and authorization_qualification.get("real_cloudflare_requests") == 0,
        "GH_MARKER_EXEC_PREMATURE_EXECUTION_STATE",
    )
    require(
        type(transport) is SyntheticGitHubRefTransport,
        "GH_MARKER_EXEC_REAL_TRANSPORT_FORBIDDEN_IN_CI",
    )

    cloudflare_real_auth_hash = authorization_qualification.get(
        "cloudflare_real_qualification_authorization_sha256"
    )
    require(
        isinstance(cloudflare_real_auth_hash, str)
        and marker_ref(cloudflare_real_auth_hash)
        == authorization_qualification.get("marker_ref"),
        "GH_MARKER_EXEC_REAL_AUTH_IDENTITY_BINDING_INVALID",
    )

    result = qualify_marker_adapter(
        transport,
        authorization_sha256=cloudflare_real_auth_hash,
        current_main_sha=authorization_qualification["current_main_sha"],
    )
    require(
        result.get("marker_ref") == authorization_qualification.get("marker_ref")
        and result.get("marker_target_sha")
        == authorization_qualification.get("marker_target_sha"),
        "GH_MARKER_EXEC_RESULT_BINDING_MISMATCH",
    )
    return {
        "artifact": "RATE_CLOUDFLARE_GITHUB_MARKER_EXECUTION_RESULT_V1",
        "validation_status": "PASS",
        "authorization_qualification_sha256":
            expected_authorization_qualification_sha256,
        "marker_ref": result["marker_ref"],
        "marker_target_sha": result["marker_target_sha"],
        "outcome": result["outcome"],
        "create_attempts": result["create_attempts"],
        "create_retries": 0,
        "readback_verified": True,
        "marker_creation_consumed": True,
        "real_transport_used": False,
        "real_github_requests": 0,
        "real_git_ref_created": False,
        "cloudflare_requests_before_marker": 0,
        "production_credit": 0,
        "cer081_credit": 0,
        "next_gate": "REAL_GITHUB_MARKER_TRANSPORT_BINDING_AND_EXECUTION",
    }

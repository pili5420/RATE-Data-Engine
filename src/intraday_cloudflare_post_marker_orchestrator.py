"""Offline post-marker Cloudflare qualification orchestration.

This composes the accepted Cloudflare qualification authorization, marker-creation
authorization, marker execution proof and the bounded HTTPS 17-request qualification
chain. No real GitHub or Cloudflare request is performed.
"""
from __future__ import annotations

import re
from typing import Any, Mapping

from .intraday_activation_candidate_review import canonical_digest
from .intraday_cloudflare_github_marker_adapter import marker_ref
from .intraday_cloudflare_https_transport_integration_rehearsal import (
    review_cloudflare_https_transport_integration,
)

HEX40 = re.compile(r"^[0-9a-f]{40}$")
HEX64 = re.compile(r"^[0-9a-f]{64}$")


class PostMarkerOrchestrationError(RuntimeError):
    pass


def require(condition: bool, reason: str) -> None:
    if not condition:
        raise PostMarkerOrchestrationError(reason)


def _sha40(value: Any, reason: str) -> str:
    text = str(value or "").lower()
    require(bool(HEX40.fullmatch(text)), reason)
    return text


def _sha64(value: Any, reason: str) -> str:
    text = str(value or "").lower()
    require(bool(HEX64.fullmatch(text)), reason)
    return text


def rehearse_post_marker_cloudflare_qualification(
    cloudflare_authorization_qualification: Mapping[str, Any],
    marker_authorization_qualification: Mapping[str, Any],
    marker_execution_result: Mapping[str, Any],
    scaffold_files: Mapping[str, str],
    *,
    expected_cloudflare_authorization_qualification_sha256: str,
    expected_marker_authorization_qualification_sha256: str,
    expected_marker_execution_result_sha256: str,
    expected_current_main_sha: str,
) -> dict[str, Any]:
    cloudflare_hash = _sha64(
        expected_cloudflare_authorization_qualification_sha256,
        "CF_POST_MARKER_EXPECTED_CLOUDFLARE_AUTH_HASH_INVALID",
    )
    marker_auth_hash = _sha64(
        expected_marker_authorization_qualification_sha256,
        "CF_POST_MARKER_EXPECTED_MARKER_AUTH_HASH_INVALID",
    )
    marker_result_hash = _sha64(
        expected_marker_execution_result_sha256,
        "CF_POST_MARKER_EXPECTED_MARKER_RESULT_HASH_INVALID",
    )
    main = _sha40(
        expected_current_main_sha,
        "CF_POST_MARKER_EXPECTED_MAIN_INVALID",
    )

    require(
        isinstance(cloudflare_authorization_qualification, Mapping)
        and canonical_digest(cloudflare_authorization_qualification) == cloudflare_hash,
        "CF_POST_MARKER_CLOUDFLARE_AUTH_HASH_MISMATCH",
    )
    require(
        cloudflare_authorization_qualification.get("artifact")
        == "RATE_CLOUDFLARE_D1_REAL_PROVIDER_QUALIFICATION_AUTHORIZATION_QUALIFICATION_V1"
        and cloudflare_authorization_qualification.get("validation_status") == "PASS"
        and cloudflare_authorization_qualification.get("current_main_sha") == main,
        "CF_POST_MARKER_CLOUDFLARE_AUTH_NOT_PASS",
    )
    require(
        cloudflare_authorization_qualification.get("single_use") is True
        and cloudflare_authorization_qualification.get("execution_consumed") is False
        and cloudflare_authorization_qualification.get("automatic_retry_allowed") is False
        and cloudflare_authorization_qualification.get("fallback_allowed") is False
        and cloudflare_authorization_qualification.get("real_cloudflare_requests") == 0
        and cloudflare_authorization_qualification.get("provider_qualified") is False,
        "CF_POST_MARKER_CLOUDFLARE_AUTH_BOUNDARY_INVALID",
    )

    real_auth_hash = _sha64(
        cloudflare_authorization_qualification.get("authorization_sha256"),
        "CF_POST_MARKER_REAL_AUTH_HASH_INVALID",
    )
    expected_ref = marker_ref(real_auth_hash)

    require(
        isinstance(marker_authorization_qualification, Mapping)
        and canonical_digest(marker_authorization_qualification) == marker_auth_hash,
        "CF_POST_MARKER_MARKER_AUTH_HASH_MISMATCH",
    )
    require(
        marker_authorization_qualification.get("artifact")
        == "RATE_CLOUDFLARE_REAL_GITHUB_MARKER_CREATION_AUTHORIZATION_QUALIFICATION_V1"
        and marker_authorization_qualification.get("validation_status") == "PASS",
        "CF_POST_MARKER_MARKER_AUTH_NOT_PASS",
    )
    require(
        marker_authorization_qualification.get("cloudflare_authorization_qualification_sha256")
        == cloudflare_hash
        and marker_authorization_qualification.get(
            "cloudflare_real_qualification_authorization_sha256"
        ) == real_auth_hash,
        "CF_POST_MARKER_MARKER_AUTH_CLOUDFLARE_BINDING_MISMATCH",
    )
    require(
        marker_authorization_qualification.get("current_main_sha") == main
        and marker_authorization_qualification.get("marker_target_sha") == main
        and marker_authorization_qualification.get("marker_ref") == expected_ref,
        "CF_POST_MARKER_MARKER_AUTH_TARGET_BINDING_MISMATCH",
    )

    require(
        isinstance(marker_execution_result, Mapping)
        and canonical_digest(marker_execution_result) == marker_result_hash,
        "CF_POST_MARKER_MARKER_RESULT_HASH_MISMATCH",
    )
    require(
        marker_execution_result.get("artifact")
        == "RATE_CLOUDFLARE_GITHUB_MARKER_EXECUTION_RESULT_V1"
        and marker_execution_result.get("validation_status") == "PASS",
        "CF_POST_MARKER_MARKER_RESULT_NOT_PASS",
    )
    require(
        marker_execution_result.get("authorization_qualification_sha256")
        == marker_auth_hash
        and marker_execution_result.get("marker_ref") == expected_ref
        and marker_execution_result.get("marker_target_sha") == main,
        "CF_POST_MARKER_MARKER_RESULT_BINDING_MISMATCH",
    )
    require(
        marker_execution_result.get("marker_creation_consumed") is True
        and marker_execution_result.get("readback_verified") is True
        and marker_execution_result.get("create_attempts") == 1
        and marker_execution_result.get("create_retries") == 0
        and marker_execution_result.get("cloudflare_requests_before_marker") == 0,
        "CF_POST_MARKER_MARKER_EXECUTION_BOUNDARY_INVALID",
    )
    require(
        marker_execution_result.get("real_transport_used") is False
        and marker_execution_result.get("real_github_requests") == 0
        and marker_execution_result.get("real_git_ref_created") is False
        and marker_execution_result.get("production_credit") == 0
        and marker_execution_result.get("cer081_credit") == 0,
        "CF_POST_MARKER_SYNTHETIC_ONLY_BOUNDARY_INVALID",
    )

    integration = review_cloudflare_https_transport_integration(
        cloudflare_authorization_qualification,
        scaffold_files,
        expected_authorization_qualification_sha256=cloudflare_hash,
        expected_current_main_sha=main,
    )
    require(
        integration.get("validation_status") == "PASS"
        and integration.get("total_requests") == 17
        and integration.get("admin_requests") == 11
        and integration.get("worker_requests") == 6
        and integration.get("connections_created") == 17
        and integration.get("connections_closed") == 17
        and integration.get("tls_hostname_verification_all") is True
        and integration.get("retry_count") == 0
        and integration.get("redirects_followed") == 0
        and integration.get("fallback_used") is False,
        "CF_POST_MARKER_HTTPS_CHAIN_INVALID",
    )
    require(
        integration.get("real_network_requests") == 0
        and integration.get("real_cloudflare_requests") == 0
        and integration.get("credentials_read") == 0
        and integration.get("real_resources_created") == 0
        and integration.get("provider_qualified") is False
        and integration.get("production_credit") == 0
        and integration.get("cer081_credit") == 0,
        "CF_POST_MARKER_HTTPS_SYNTHETIC_BOUNDARY_INVALID",
    )

    return {
        "artifact": "RATE_CLOUDFLARE_POST_MARKER_QUALIFICATION_ORCHESTRATION_V1",
        "validation_status": "PASS",
        "cloudflare_authorization_qualification_sha256": cloudflare_hash,
        "marker_authorization_qualification_sha256": marker_auth_hash,
        "marker_execution_result_sha256": marker_result_hash,
        "current_main_sha": main,
        "marker_ref": expected_ref,
        "marker_target_sha": main,
        "marker_gate_passed": True,
        "cloudflare_requests_before_marker": 0,
        "synthetic_cloudflare_requests_after_marker": 17,
        "admin_requests": 11,
        "worker_requests": 6,
        "retry_count": 0,
        "redirects_followed": 0,
        "fallback_used": False,
        "real_github_requests": 0,
        "real_git_ref_created": False,
        "real_network_requests": 0,
        "real_cloudflare_requests": 0,
        "credentials_read": 0,
        "real_resources_created": 0,
        "provider_qualified": False,
        "production_credit": 0,
        "cer081_credit": 0,
        "next_gate": "EXPLICIT_REAL_GITHUB_MARKER_EXECUTION_THEN_CLOUDFLARE_QUALIFICATION",
    }

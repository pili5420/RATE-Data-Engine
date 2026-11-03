"""Pure validator for one explicit Cloudflare D1 real-provider qualification authorization.

This gate binds the exact plan and pre-live engineering evidence to one single-use
Control Center authorization. It performs no Cloudflare request and reads no secret.
"""
from __future__ import annotations

import re
from typing import Any, Mapping

from .intraday_activation_candidate_review import canonical_digest

HEX40 = re.compile(r"^[0-9a-f]{40}$")
HEX64 = re.compile(r"^[0-9a-f]{64}$")
DECISION = re.compile(r"^[A-Za-z0-9._-]{1,96}$")

EXPECTED_RESOURCE_BUDGET = {
    "create_d1_database": 1,
    "create_worker_script": 1,
    "create_worker_secret": 1,
    "custom_routes": 0,
    "custom_domains": 0,
    "durable_objects": 0,
    "kv_namespaces": 0,
    "r2_buckets": 0,
    "qualification_only": True,
    "persist_after_qualification": False,
}
EXPECTED_ADMIN_BUDGET = {
    "CREATE_D1_DATABASE": 1,
    "UPLOAD_WORKER_MODULE": 1,
    "PUT_WORKER_SECRET": 1,
    "APPLY_D1_SCHEMA": 1,
    "GET_D1_METADATA": 1,
    "GET_WORKER_SCRIPT": 1,
    "GET_WORKER_SECRET_METADATA": 1,
}
EXPECTED_RUNTIME_BUDGET = {
    "UNAUTHORIZED_GET": 1,
    "MISSING_GET": 1,
    "CREATE_POST": 1,
    "READBACK_GET": 1,
    "DUPLICATE_POST": 1,
    "UNSUPPORTED_METHOD": 1,
}
EXPECTED_CLEANUP_BUDGET = {
    "DELETE_WORKER_SCRIPT": 1,
    "DELETE_D1_DATABASE": 1,
}


class CloudflareQualificationAuthorizationError(RuntimeError):
    pass


def require(condition: bool, reason: str) -> None:
    if not condition:
        raise CloudflareQualificationAuthorizationError(reason)


def _sha40(value: Any, reason: str) -> str:
    text = str(value or "").lower()
    require(bool(HEX40.fullmatch(text)), reason)
    return text


def _sha64(value: Any, reason: str) -> str:
    text = str(value or "").lower()
    require(bool(HEX64.fullmatch(text)), reason)
    return text


def validate_cloudflare_real_qualification_authorization(
    authorization: Mapping[str, Any],
    plan_review: Mapping[str, Any],
    *,
    expected_authorization_sha256: str,
    expected_plan_review_sha256: str,
    expected_current_main_sha: str,
    expected_scaffold_sha256: str,
    expected_node_review_sha256: str,
    expected_control_center_decision_id: str,
) -> dict[str, Any]:
    auth_hash = _sha64(expected_authorization_sha256, "CF_AUTH_EXPECTED_AUTHORIZATION_HASH_INVALID")
    plan_hash = _sha64(expected_plan_review_sha256, "CF_AUTH_EXPECTED_PLAN_HASH_INVALID")
    main_sha = _sha40(expected_current_main_sha, "CF_AUTH_EXPECTED_MAIN_INVALID")
    scaffold_hash = _sha64(expected_scaffold_sha256, "CF_AUTH_EXPECTED_SCAFFOLD_HASH_INVALID")
    node_hash = _sha64(expected_node_review_sha256, "CF_AUTH_EXPECTED_NODE_REVIEW_HASH_INVALID")
    require(
        isinstance(expected_control_center_decision_id, str)
        and bool(DECISION.fullmatch(expected_control_center_decision_id))
        and ".." not in expected_control_center_decision_id
        and not expected_control_center_decision_id.endswith(".")
        and not expected_control_center_decision_id.lower().endswith(".lock"),
        "CF_AUTH_EXPECTED_DECISION_ID_INVALID",
    )

    require(isinstance(plan_review, Mapping), "CF_AUTH_PLAN_REVIEW_INVALID")
    require(canonical_digest(plan_review) == plan_hash, "CF_AUTH_PLAN_REVIEW_HASH_MISMATCH")
    require(
        plan_review.get("artifact")
        == "RATE_CLOUDFLARE_D1_REAL_PROVIDER_QUALIFICATION_PLAN_REVIEW_V1"
        and plan_review.get("validation_status") == "PASS"
        and plan_review.get("provider") == "CLOUDFLARE_WORKERS_D1"
        and plan_review.get("plan") == "WORKERS_FREE"
        and plan_review.get("qualification_scope") == "TEMPORARY_RESOURCES_ONLY",
        "CF_AUTH_PLAN_REVIEW_NOT_PASS",
    )
    require(plan_review.get("resource_budget") == EXPECTED_RESOURCE_BUDGET,
            "CF_AUTH_RESOURCE_BUDGET_INVALID")
    require(plan_review.get("admin_operation_budget") == EXPECTED_ADMIN_BUDGET,
            "CF_AUTH_ADMIN_BUDGET_INVALID")
    require(plan_review.get("runtime_probe_budget") == EXPECTED_RUNTIME_BUDGET,
            "CF_AUTH_RUNTIME_BUDGET_INVALID")
    require(plan_review.get("cleanup_operation_budget") == EXPECTED_CLEANUP_BUDGET,
            "CF_AUTH_CLEANUP_BUDGET_INVALID")
    require(
        plan_review.get("automatic_retry_allowed") is False
        and plan_review.get("fallback_allowed") is False
        and plan_review.get("qualification_executed") is False
        and plan_review.get("provider_qualified") is False
        and plan_review.get("real_cloudflare_requests") == 0
        and plan_review.get("credentials_read") == 0
        and plan_review.get("resources_created") == 0
        and plan_review.get("production_credit") == 0
        and plan_review.get("cer081_credit") == 0,
        "CF_AUTH_PLAN_BOUNDARY_INVALID",
    )

    require(isinstance(authorization, Mapping), "CF_AUTHORIZATION_INVALID")
    require(canonical_digest(authorization) == auth_hash, "CF_AUTHORIZATION_HASH_MISMATCH")
    require(
        authorization.get("artifact")
        == "RATE_CLOUDFLARE_D1_REAL_PROVIDER_QUALIFICATION_AUTHORIZATION_V1"
        and authorization.get("status") == "CLOUDFLARE_REAL_QUALIFICATION_AUTHORIZED",
        "CF_AUTHORIZATION_STATUS_INVALID",
    )
    require(
        authorization.get("control_center_decision_id") == expected_control_center_decision_id,
        "CF_AUTHORIZATION_DECISION_ID_MISMATCH",
    )
    require(authorization.get("current_main_sha") == main_sha,
            "CF_AUTHORIZATION_MAIN_MISMATCH")
    require(
        authorization.get("plan_review_sha256") == plan_hash
        and authorization.get("scaffold_sha256") == scaffold_hash
        and authorization.get("node_review_sha256") == node_hash,
        "CF_AUTHORIZATION_EVIDENCE_BINDING_MISMATCH",
    )
    require(
        authorization.get("provider") == "CLOUDFLARE_WORKERS_D1"
        and authorization.get("plan") == "WORKERS_FREE",
        "CF_AUTHORIZATION_PROVIDER_INVALID",
    )
    require(
        authorization.get("single_use") is True
        and authorization.get("execution_consumed") is False
        and authorization.get("automatic_retry_allowed") is False
        and authorization.get("fallback_allowed") is False,
        "CF_AUTHORIZATION_SINGLE_USE_BOUNDARY_INVALID",
    )
    require(authorization.get("resource_budget") == EXPECTED_RESOURCE_BUDGET,
            "CF_AUTHORIZATION_RESOURCE_BUDGET_INVALID")
    require(authorization.get("admin_operation_budget") == EXPECTED_ADMIN_BUDGET,
            "CF_AUTHORIZATION_ADMIN_BUDGET_INVALID")
    require(authorization.get("runtime_probe_budget") == EXPECTED_RUNTIME_BUDGET,
            "CF_AUTHORIZATION_RUNTIME_BUDGET_INVALID")
    require(authorization.get("cleanup_operation_budget") == EXPECTED_CLEANUP_BUDGET,
            "CF_AUTHORIZATION_CLEANUP_BUDGET_INVALID")
    require(
        authorization.get("api_token_secret_name") == "CLOUDFLARE_API_TOKEN"
        and authorization.get("account_id_variable_name") == "CLOUDFLARE_ACCOUNT_ID"
        and authorization.get("worker_secret_name") == "RATE_D1_RECEIPT_WORKER_TOKEN"
        and authorization.get("credential_value_embedded") is False,
        "CF_AUTHORIZATION_CREDENTIAL_BOUNDARY_INVALID",
    )
    require(
        authorization.get("d1_read_replication") == "disabled"
        and authorization.get("workers_endpoint") == "WORKERS_DEV_ONLY"
        and authorization.get("cleanup_required") is True
        and authorization.get("qualification_credit_requires_cleanup_success") is True
        and authorization.get("residual_resource_disposition") == "BLOCKED_RESIDUAL_RESOURCE",
        "CF_AUTHORIZATION_PROVIDER_BOUNDARY_INVALID",
    )
    require(
        authorization.get("qualification_execution_performed") is False
        and authorization.get("real_cloudflare_requests") == 0
        and authorization.get("credentials_read") == 0
        and authorization.get("resources_created") == 0
        and authorization.get("provider_qualified") is False
        and authorization.get("production_credit") == 0
        and authorization.get("cer081_credit") == 0,
        "CF_AUTHORIZATION_PREMATURE_EXECUTION_OR_CREDIT",
    )

    return {
        "artifact": "RATE_CLOUDFLARE_D1_REAL_PROVIDER_QUALIFICATION_AUTHORIZATION_QUALIFICATION_V1",
        "validation_status": "PASS",
        "authorization_sha256": auth_hash,
        "plan_review_sha256": plan_hash,
        "scaffold_sha256": scaffold_hash,
        "node_review_sha256": node_hash,
        "current_main_sha": main_sha,
        "control_center_decision_id": expected_control_center_decision_id,
        "provider": "CLOUDFLARE_WORKERS_D1",
        "plan": "WORKERS_FREE",
        "single_use": True,
        "execution_consumed": False,
        "automatic_retry_allowed": False,
        "fallback_allowed": False,
        "resource_budget": dict(EXPECTED_RESOURCE_BUDGET),
        "admin_operation_budget": dict(EXPECTED_ADMIN_BUDGET),
        "runtime_probe_budget": dict(EXPECTED_RUNTIME_BUDGET),
        "cleanup_operation_budget": dict(EXPECTED_CLEANUP_BUDGET),
        "cleanup_required": True,
        "qualification_credit_requires_cleanup_success": True,
        "qualification_execution_allowed_by_validator": False,
        "qualification_execution_performed": False,
        "real_cloudflare_requests": 0,
        "credentials_read": 0,
        "resources_created": 0,
        "provider_qualified": False,
        "production_credit": 0,
        "cer081_credit": 0,
        "next_gate": "SEPARATE_CLOUDFLARE_REAL_QUALIFICATION_EXECUTOR",
    }

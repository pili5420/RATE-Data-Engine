"""Validate explicit authorization for one real Git transaction execution.

This validator does not execute Git operations. It binds a reviewed transaction
plan and synthetic rehearsal to an exact real Git operation budget.
"""
from __future__ import annotations

import re
from typing import Any, Mapping

from .intraday_activation_candidate_review import canonical_digest

HEX40 = re.compile(r"^[0-9a-f]{40}$")
HEX64 = re.compile(r"^[0-9a-f]{64}$")
REF_SAFE = re.compile(r"^[A-Za-z0-9._/-]{1,180}$")

EXPECTED_BUDGET = {
    "create_blob_count": 9,
    "create_tree_count": 1,
    "create_commit_count": 1,
    "create_branch_ref_count": 1,
    "create_draft_pull_request_count": 1,
    "update_main_ref_count": 0,
    "merge_count": 0,
}


class RealGitExecutionAuthorizationError(RuntimeError):
    pass


def require(condition: bool, reason: str) -> None:
    if not condition:
        raise RealGitExecutionAuthorizationError(reason)


def _sha40(value: Any, reason: str) -> str:
    text = str(value or "").lower()
    require(bool(HEX40.fullmatch(text)), reason)
    return text


def _sha64(value: Any, reason: str) -> str:
    text = str(value or "").lower()
    require(bool(HEX64.fullmatch(text)), reason)
    return text


def _valid_branch(value: Any) -> bool:
    return (
        isinstance(value, str)
        and bool(REF_SAFE.fullmatch(value))
        and value.startswith("activation/rate-v11-intraday-")
        and value != "main"
        and ".." not in value
        and not value.endswith(".")
        and not value.lower().endswith(".lock")
    )


def validate_real_git_execution_authorization(
    authorization: Mapping[str, Any],
    transaction_plan: Mapping[str, Any],
    rehearsal: Mapping[str, Any],
    *,
    expected_authorization_sha256: str,
    expected_transaction_plan_sha256: str,
    expected_rehearsal_sha256: str,
    expected_base_main_sha: str,
    expected_candidate_manifest_sha256: str,
    expected_target_branch: str,
    expected_provider_name: str,
    expected_decision_id: str,
) -> dict[str, Any]:
    auth_hash = _sha64(
        expected_authorization_sha256,
        "REAL_GIT_AUTH_EXPECTED_AUTHORIZATION_HASH_INVALID",
    )
    plan_hash = _sha64(
        expected_transaction_plan_sha256,
        "REAL_GIT_AUTH_EXPECTED_PLAN_HASH_INVALID",
    )
    rehearsal_hash = _sha64(
        expected_rehearsal_sha256,
        "REAL_GIT_AUTH_EXPECTED_REHEARSAL_HASH_INVALID",
    )
    base_main = _sha40(
        expected_base_main_sha,
        "REAL_GIT_AUTH_EXPECTED_MAIN_INVALID",
    )
    manifest_hash = _sha64(
        expected_candidate_manifest_sha256,
        "REAL_GIT_AUTH_EXPECTED_MANIFEST_HASH_INVALID",
    )
    require(_valid_branch(expected_target_branch),
            "REAL_GIT_AUTH_EXPECTED_BRANCH_INVALID")
    require(
        isinstance(expected_provider_name, str) and expected_provider_name.strip(),
        "REAL_GIT_AUTH_EXPECTED_PROVIDER_INVALID",
    )
    require(
        isinstance(expected_decision_id, str) and expected_decision_id.strip(),
        "REAL_GIT_AUTH_EXPECTED_DECISION_ID_INVALID",
    )

    require(isinstance(transaction_plan, Mapping), "REAL_GIT_AUTH_PLAN_INVALID")
    require(
        canonical_digest(transaction_plan) == plan_hash,
        "REAL_GIT_AUTH_PLAN_HASH_MISMATCH",
    )
    require(
        transaction_plan.get("artifact")
        == "RATE_INTRADAY_ACTIVATION_APPLY_TRANSACTION_PLAN_V1"
        and transaction_plan.get("status") == "TRANSACTION_PLAN_ONLY",
        "REAL_GIT_AUTH_PLAN_STATUS_INVALID",
    )
    require(
        transaction_plan.get("base_main_sha") == base_main,
        "REAL_GIT_AUTH_PLAN_MAIN_MISMATCH",
    )
    require(
        transaction_plan.get("candidate_manifest_sha256") == manifest_hash,
        "REAL_GIT_AUTH_PLAN_MANIFEST_MISMATCH",
    )
    require(
        transaction_plan.get("target_branch") == expected_target_branch
        and transaction_plan.get("target_base") == "main",
        "REAL_GIT_AUTH_PLAN_BRANCH_MISMATCH",
    )
    require(
        transaction_plan.get("provider_name") == expected_provider_name,
        "REAL_GIT_AUTH_PLAN_PROVIDER_MISMATCH",
    )
    require(
        transaction_plan.get("single_use") is True
        and transaction_plan.get("automatic_retry_allowed") is False
        and transaction_plan.get("fallback_allowed") is False
        and transaction_plan.get("merge_allowed_by_plan") is False
        and transaction_plan.get("direct_main_update_allowed") is False
        and transaction_plan.get("apply_executed") is False
        and transaction_plan.get("repository_writes") == 0
        and transaction_plan.get("live_provider_requests") == 0
        and transaction_plan.get("external_dependency_resolved") is False
        and transaction_plan.get("registry_activation_allowed") is False
        and transaction_plan.get("production_credit") == 0
        and transaction_plan.get("cer081_credit") == 0,
        "REAL_GIT_AUTH_PLAN_BOUNDARY_INVALID",
    )

    require(isinstance(rehearsal, Mapping), "REAL_GIT_AUTH_REHEARSAL_INVALID")
    require(
        canonical_digest(rehearsal) == rehearsal_hash,
        "REAL_GIT_AUTH_REHEARSAL_HASH_MISMATCH",
    )
    require(
        rehearsal.get("artifact")
        == "RATE_INTRADAY_ACTIVATION_GIT_TRANSACTION_REHEARSAL_V1"
        and rehearsal.get("validation_status") == "PASS"
        and rehearsal.get("transport") == "SYNTHETIC_IN_MEMORY_ONLY",
        "REAL_GIT_AUTH_REHEARSAL_NOT_PASS",
    )
    require(
        rehearsal.get("transaction_plan_sha256") == plan_hash
        and rehearsal.get("base_main_sha") == base_main
        and rehearsal.get("candidate_manifest_sha256") == manifest_hash
        and rehearsal.get("synthetic_branch") == expected_target_branch,
        "REAL_GIT_AUTH_REHEARSAL_BINDING_MISMATCH",
    )
    require(
        rehearsal.get("blob_count") == 9
        and rehearsal.get("single_use_consumed") is True
        and rehearsal.get("retry_allowed") is False
        and rehearsal.get("main_ref_unchanged") is True
        and rehearsal.get("branch_ref_created_last") is True
        and rehearsal.get("real_git_objects_created") == 0
        and rehearsal.get("real_repository_writes") == 0
        and rehearsal.get("real_branch_created") is False
        and rehearsal.get("real_pull_request_created") is False
        and rehearsal.get("merge_performed") is False
        and rehearsal.get("live_provider_requests") == 0
        and rehearsal.get("external_dependency_resolved") is False
        and rehearsal.get("registry_activation_allowed") is False
        and rehearsal.get("production_credit") == 0
        and rehearsal.get("cer081_credit") == 0,
        "REAL_GIT_AUTH_REHEARSAL_BOUNDARY_INVALID",
    )

    require(isinstance(authorization, Mapping), "REAL_GIT_AUTHORIZATION_INVALID")
    require(
        canonical_digest(authorization) == auth_hash,
        "REAL_GIT_AUTHORIZATION_HASH_MISMATCH",
    )
    require(
        authorization.get("artifact")
        == "RATE_INTRADAY_REAL_GIT_TRANSACTION_EXECUTION_AUTHORIZATION_V1"
        and authorization.get("status")
        == "REAL_GIT_TRANSACTION_EXECUTION_AUTHORIZED",
        "REAL_GIT_AUTHORIZATION_STATUS_INVALID",
    )
    require(
        authorization.get("control_center_decision_id") == expected_decision_id,
        "REAL_GIT_AUTH_DECISION_ID_MISMATCH",
    )
    require(
        authorization.get("base_main_sha") == base_main
        and authorization.get("transaction_plan_sha256") == plan_hash
        and authorization.get("rehearsal_sha256") == rehearsal_hash
        and authorization.get("candidate_manifest_sha256") == manifest_hash,
        "REAL_GIT_AUTHORIZATION_EVIDENCE_BINDING_MISMATCH",
    )
    require(
        authorization.get("target_branch") == expected_target_branch
        and authorization.get("target_base") == "main",
        "REAL_GIT_AUTHORIZATION_BRANCH_MISMATCH",
    )
    require(
        authorization.get("provider_name") == expected_provider_name,
        "REAL_GIT_AUTHORIZATION_PROVIDER_MISMATCH",
    )
    require(
        authorization.get("single_use") is True
        and authorization.get("automatic_retry_allowed") is False
        and authorization.get("fallback_allowed") is False,
        "REAL_GIT_AUTHORIZATION_SINGLE_USE_BOUNDARY_INVALID",
    )
    require(
        authorization.get("operation_budget") == EXPECTED_BUDGET,
        "REAL_GIT_AUTHORIZATION_OPERATION_BUDGET_INVALID",
    )
    require(
        authorization.get("draft_pull_request_required") is True
        and authorization.get("pull_request_base") == "main"
        and authorization.get("direct_main_update_allowed") is False
        and authorization.get("merge_allowed") is False,
        "REAL_GIT_AUTHORIZATION_PR_BOUNDARY_INVALID",
    )
    require(
        authorization.get("live_provider_requests_allowed") == 0
        and authorization.get("credential_value_embedded") is False
        and authorization.get("production_credit_before_execution") == 0
        and authorization.get("cer081_credit_before_execution") == 0,
        "REAL_GIT_AUTHORIZATION_PRODUCTION_BOUNDARY_INVALID",
    )

    return {
        "artifact": "RATE_INTRADAY_REAL_GIT_TRANSACTION_EXECUTION_AUTHORIZATION_QUALIFICATION_V1",
        "validation_status": "PASS",
        "control_center_decision_id": expected_decision_id,
        "authorization_sha256": auth_hash,
        "transaction_plan_sha256": plan_hash,
        "rehearsal_sha256": rehearsal_hash,
        "base_main_sha": base_main,
        "candidate_manifest_sha256": manifest_hash,
        "target_branch": expected_target_branch,
        "target_base": "main",
        "provider_name": expected_provider_name,
        "operation_budget": dict(EXPECTED_BUDGET),
        "single_use": True,
        "retry_allowed": False,
        "draft_pull_request_required": True,
        "direct_main_update_allowed": False,
        "merge_allowed": False,
        "authorization_valid": True,
        "execution_performed": False,
        "real_git_operations": 0,
        "live_provider_requests": 0,
        "external_dependency_resolved": False,
        "registry_activation_allowed": False,
        "production_credit": 0,
        "cer081_credit": 0,
        "next_gate": "SEPARATE_REAL_GIT_TRANSACTION_EXECUTOR",
    }

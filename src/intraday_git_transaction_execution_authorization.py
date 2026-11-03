"""Pure qualification for one explicit real Git transaction execution authorization.

This validator does not create Git objects, refs, branches, pull requests or merges.
It only proves that one external Control Center authorization is bound to one exact
transaction plan, one exact synthetic rehearsal result, one exact current main and
one exact dedicated target branch.
"""
from __future__ import annotations

import re
from typing import Any, Mapping

from .intraday_activation_apply_authorization import EXPECTED_PATHS
from .intraday_activation_candidate_review import canonical_digest

HEX40 = re.compile(r"^[0-9a-f]{40}$")
HEX64 = re.compile(r"^[0-9a-f]{64}$")
DECISION_ID = re.compile(r"^[A-Za-z0-9._-]{1,96}$")
ALLOWED_OPERATIONS = {
    "CREATE_BLOBS",
    "CREATE_TREE",
    "CREATE_COMMIT",
    "CREATE_BRANCH_REF",
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


def validate_real_git_transaction_execution_authorization(
    authorization: Mapping[str, Any],
    transaction_plan: Mapping[str, Any],
    rehearsal_result: Mapping[str, Any],
    *,
    expected_authorization_sha256: str,
    expected_transaction_plan_sha256: str,
    expected_rehearsal_sha256: str,
    expected_current_main_sha: str,
    expected_target_branch: str,
    expected_control_center_decision_id: str,
    expected_provider_name: str,
) -> dict[str, Any]:
    authorization_hash = _sha64(
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
    current_main = _sha40(
        expected_current_main_sha,
        "REAL_GIT_AUTH_EXPECTED_MAIN_INVALID",
    )
    require(
        isinstance(expected_target_branch, str)
        and expected_target_branch.startswith("activation/rate-v11-intraday-")
        and expected_target_branch != "main"
        and ".." not in expected_target_branch
        and not expected_target_branch.endswith(".")
        and not expected_target_branch.lower().endswith(".lock"),
        "REAL_GIT_AUTH_EXPECTED_TARGET_BRANCH_INVALID",
    )
    require(
        isinstance(expected_control_center_decision_id, str)
        and bool(DECISION_ID.fullmatch(expected_control_center_decision_id)),
        "REAL_GIT_AUTH_EXPECTED_DECISION_ID_INVALID",
    )
    require(
        isinstance(expected_provider_name, str)
        and expected_provider_name.strip(),
        "REAL_GIT_AUTH_EXPECTED_PROVIDER_INVALID",
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
        transaction_plan.get("base_main_sha") == current_main,
        "REAL_GIT_AUTH_PLAN_MAIN_MISMATCH",
    )
    require(
        transaction_plan.get("target_branch") == expected_target_branch,
        "REAL_GIT_AUTH_PLAN_BRANCH_MISMATCH",
    )
    require(
        transaction_plan.get("provider_name") == expected_provider_name,
        "REAL_GIT_AUTH_PLAN_PROVIDER_MISMATCH",
    )
    require(
        transaction_plan.get("control_center_decision_id")
        == expected_control_center_decision_id,
        "REAL_GIT_AUTH_PLAN_DECISION_ID_MISMATCH",
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
    require(
        isinstance(transaction_plan.get("files"), Mapping)
        and set(transaction_plan["files"]) == set(EXPECTED_PATHS),
        "REAL_GIT_AUTH_PLAN_FILE_SET_INVALID",
    )

    require(isinstance(rehearsal_result, Mapping), "REAL_GIT_AUTH_REHEARSAL_INVALID")
    require(
        canonical_digest(rehearsal_result) == rehearsal_hash,
        "REAL_GIT_AUTH_REHEARSAL_HASH_MISMATCH",
    )
    require(
        rehearsal_result.get("artifact")
        == "RATE_INTRADAY_ACTIVATION_GIT_TRANSACTION_REHEARSAL_V1"
        and rehearsal_result.get("validation_status") == "PASS"
        and rehearsal_result.get("transport") == "SYNTHETIC_IN_MEMORY_ONLY",
        "REAL_GIT_AUTH_REHEARSAL_NOT_PASS",
    )
    require(
        rehearsal_result.get("transaction_plan_sha256") == plan_hash
        and rehearsal_result.get("base_main_sha") == current_main
        and rehearsal_result.get("candidate_manifest_sha256")
        == transaction_plan.get("candidate_manifest_sha256")
        and rehearsal_result.get("synthetic_branch") == expected_target_branch,
        "REAL_GIT_AUTH_REHEARSAL_BINDING_MISMATCH",
    )
    require(
        rehearsal_result.get("blob_count") == 9
        and rehearsal_result.get("single_use_consumed") is True
        and rehearsal_result.get("retry_allowed") is False
        and rehearsal_result.get("main_ref_unchanged") is True
        and rehearsal_result.get("branch_ref_created_last") is True
        and rehearsal_result.get("real_git_objects_created") == 0
        and rehearsal_result.get("real_repository_writes") == 0
        and rehearsal_result.get("real_branch_created") is False
        and rehearsal_result.get("real_pull_request_created") is False
        and rehearsal_result.get("merge_performed") is False
        and rehearsal_result.get("live_provider_requests") == 0
        and rehearsal_result.get("external_dependency_resolved") is False
        and rehearsal_result.get("registry_activation_allowed") is False
        and rehearsal_result.get("production_credit") == 0
        and rehearsal_result.get("cer081_credit") == 0,
        "REAL_GIT_AUTH_REHEARSAL_BOUNDARY_INVALID",
    )

    require(isinstance(authorization, Mapping), "REAL_GIT_AUTHORIZATION_INVALID")
    require(
        canonical_digest(authorization) == authorization_hash,
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
        authorization.get("control_center_decision_id")
        == expected_control_center_decision_id,
        "REAL_GIT_AUTHORIZATION_DECISION_ID_MISMATCH",
    )
    require(
        authorization.get("current_main_sha") == current_main,
        "REAL_GIT_AUTHORIZATION_MAIN_MISMATCH",
    )
    require(
        authorization.get("transaction_plan_sha256") == plan_hash
        and authorization.get("rehearsal_sha256") == rehearsal_hash
        and authorization.get("candidate_manifest_sha256")
        == transaction_plan.get("candidate_manifest_sha256"),
        "REAL_GIT_AUTHORIZATION_EVIDENCE_BINDING_MISMATCH",
    )
    require(
        authorization.get("provider_name") == expected_provider_name
        and authorization.get("target_branch") == expected_target_branch,
        "REAL_GIT_AUTHORIZATION_TARGET_BINDING_MISMATCH",
    )
    require(
        authorization.get("single_use") is True
        and authorization.get("execution_consumed") is False
        and authorization.get("automatic_retry_allowed") is False
        and authorization.get("fallback_allowed") is False,
        "REAL_GIT_AUTHORIZATION_SINGLE_USE_BOUNDARY_INVALID",
    )
    require(
        set(authorization.get("allowed_operations", [])) == ALLOWED_OPERATIONS,
        "REAL_GIT_AUTHORIZATION_OPERATIONS_INVALID",
    )
    require(
        set(authorization.get("allowed_paths", [])) == set(EXPECTED_PATHS),
        "REAL_GIT_AUTHORIZATION_PATHS_INVALID",
    )
    require(
        authorization.get("max_blob_count") == 9
        and authorization.get("max_tree_count") == 1
        and authorization.get("max_commit_count") == 1
        and authorization.get("max_ref_count") == 1
        and authorization.get("branch_ref_must_be_last") is True,
        "REAL_GIT_AUTHORIZATION_OBJECT_BUDGET_INVALID",
    )
    require(
        authorization.get("direct_main_update_allowed") is False
        and authorization.get("pull_request_creation_allowed") is False
        and authorization.get("merge_allowed") is False
        and authorization.get("branch_delete_allowed") is False
        and authorization.get("credential_value_embedded") is False
        and authorization.get("live_provider_requests_allowed") == 0
        and authorization.get("production_credit_before_execution") == 0
        and authorization.get("cer081_credit_before_execution") == 0,
        "REAL_GIT_AUTHORIZATION_FORBIDDEN_ACTION_BOUNDARY_INVALID",
    )

    return {
        "artifact": "RATE_INTRADAY_REAL_GIT_TRANSACTION_EXECUTION_AUTHORIZATION_QUALIFICATION_V1",
        "validation_status": "PASS",
        "authorization_sha256": authorization_hash,
        "transaction_plan_sha256": plan_hash,
        "rehearsal_sha256": rehearsal_hash,
        "current_main_sha": current_main,
        "control_center_decision_id": expected_control_center_decision_id,
        "provider_name": expected_provider_name,
        "target_branch": expected_target_branch,
        "candidate_manifest_sha256": transaction_plan["candidate_manifest_sha256"],
        "single_use": True,
        "execution_consumed": False,
        "automatic_retry_allowed": False,
        "fallback_allowed": False,
        "allowed_operations": sorted(ALLOWED_OPERATIONS),
        "allowed_paths": list(EXPECTED_PATHS),
        "max_blob_count": 9,
        "max_tree_count": 1,
        "max_commit_count": 1,
        "max_ref_count": 1,
        "branch_ref_must_be_last": True,
        "direct_main_update_allowed": False,
        "pull_request_creation_allowed": False,
        "merge_allowed": False,
        "branch_delete_allowed": False,
        "execution_performed": False,
        "repository_writes": 0,
        "live_provider_requests": 0,
        "external_dependency_resolved": False,
        "registry_activation_allowed": False,
        "production_credit": 0,
        "cer081_credit": 0,
        "next_gate": "SEPARATE_REAL_GIT_TRANSACTION_EXECUTOR",
    }

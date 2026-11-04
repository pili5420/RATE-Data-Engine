"""Offline orchestration rehearsal: durable receipt first, then synthetic Git transaction.

The module composes #151 readiness, #127 write-once receipt fencing and #123 synthetic
Git transaction semantics. It never contacts a real authority store or GitHub.
"""
from __future__ import annotations

import hashlib
from typing import Any, Mapping

from .intraday_activation_apply_authorization import EXPECTED_PATHS
from .intraday_activation_candidate_materialization import candidate_manifest_sha256
from .intraday_activation_candidate_review import canonical_digest
from .intraday_git_transaction_rehearsal import (
    SyntheticGitBackend,
    rehearse_activation_git_transaction,
)
from .intraday_real_git_execution_authorization import EXPECTED_BUDGET
from .intraday_real_git_execution_fence import (
    SyntheticWriteOnceReceiptStore,
    consume_execution_fence,
    validate_consumed_execution_fence,
)


class DurableReceiptGitOrchestrationError(RuntimeError):
    pass


def require(condition: bool, reason: str) -> None:
    if not condition:
        raise DurableReceiptGitOrchestrationError(reason)


def _git_blob_sha1(content: bytes) -> str:
    return hashlib.sha1(
        f"blob {len(content)}\0".encode("ascii") + content
    ).hexdigest()


def _preflight(
    readiness: Mapping[str, Any],
    real_git_authorization: Mapping[str, Any],
    transaction_plan: Mapping[str, Any],
    candidate_files: Mapping[str, str],
    receipt_store: SyntheticWriteOnceReceiptStore,
    git_backend: SyntheticGitBackend,
    *,
    expected_readiness_sha256: str,
    expected_real_git_authorization_sha256: str,
    expected_transaction_plan_sha256: str,
    expected_candidate_manifest_sha256: str,
) -> tuple[str, str, str, str]:
    require(
        canonical_digest(readiness) == expected_readiness_sha256,
        "DURABLE_GIT_READINESS_HASH_MISMATCH",
    )
    require(
        readiness.get("artifact")
        == "RATE_REAL_GIT_EXECUTION_WITH_ACCEPTED_AUTHORITY_STORE_READINESS_V1"
        and readiness.get("validation_status") == "PASS",
        "DURABLE_GIT_READINESS_NOT_PASS",
    )
    require(
        readiness.get("authority_store_provider") == "CLOUDFLARE_WORKERS_D1"
        and readiness.get("authority_store_role")
        == "REAL_GIT_EXECUTION_CONSUMPTION_RECEIPT_STORE"
        and readiness.get("authority_store_provider_accepted") is True
        and readiness.get("authority_store_provider_qualified") is True,
        "DURABLE_GIT_STORE_NOT_ACCEPTED",
    )
    require(
        readiness.get("persist_receipt_before_first_git_mutation") is True
        and readiness.get("write_once_receipt_required") is True
        and readiness.get("receipt_retry_after_consumption_allowed") is False
        and readiness.get("receipt_consumed") is False
        and readiness.get("readiness_only") is True
        and readiness.get("real_git_transaction_execution_allowed") is False,
        "DURABLE_GIT_READINESS_BOUNDARY_INVALID",
    )
    require(
        readiness.get("operation_budget") == EXPECTED_BUDGET
        and readiness.get("real_git_operations") == 0
        and readiness.get("live_provider_requests") == 0
        and readiness.get("external_intraday_dependency_resolved") is False
        and readiness.get("production_credit") == 0
        and readiness.get("cer081_credit") == 0,
        "DURABLE_GIT_READINESS_PREMATURE_STATE",
    )

    require(
        canonical_digest(real_git_authorization)
        == expected_real_git_authorization_sha256,
        "DURABLE_GIT_AUTHORIZATION_HASH_MISMATCH",
    )
    require(
        real_git_authorization.get("artifact")
        == "RATE_INTRADAY_REAL_GIT_TRANSACTION_EXECUTION_AUTHORIZATION_QUALIFICATION_V1"
        and real_git_authorization.get("validation_status") == "PASS"
        and real_git_authorization.get("authorization_valid") is True,
        "DURABLE_GIT_AUTHORIZATION_NOT_PASS",
    )

    main_sha = readiness.get("current_main_sha")
    target_branch = readiness.get("target_branch")
    provider_name = readiness.get("intraday_provider_name")
    require(
        real_git_authorization.get("base_main_sha") == main_sha
        and real_git_authorization.get("target_branch") == target_branch
        and real_git_authorization.get("provider_name") == provider_name,
        "DURABLE_GIT_AUTHORIZATION_READINESS_BINDING_MISMATCH",
    )
    require(
        real_git_authorization.get("operation_budget") == EXPECTED_BUDGET
        and real_git_authorization.get("single_use") is True
        and real_git_authorization.get("retry_allowed") is False
        and real_git_authorization.get("draft_pull_request_required") is True
        and real_git_authorization.get("direct_main_update_allowed") is False
        and real_git_authorization.get("merge_allowed") is False
        and real_git_authorization.get("execution_performed") is False
        and real_git_authorization.get("real_git_operations") == 0,
        "DURABLE_GIT_AUTHORIZATION_BOUNDARY_INVALID",
    )

    require(
        canonical_digest(transaction_plan) == expected_transaction_plan_sha256,
        "DURABLE_GIT_PLAN_HASH_MISMATCH",
    )
    require(
        transaction_plan.get("artifact")
        == "RATE_INTRADAY_ACTIVATION_APPLY_TRANSACTION_PLAN_V1"
        and transaction_plan.get("status") == "TRANSACTION_PLAN_ONLY",
        "DURABLE_GIT_PLAN_NOT_VALID",
    )
    require(
        real_git_authorization.get("transaction_plan_sha256")
        == expected_transaction_plan_sha256
        and transaction_plan.get("base_main_sha") == main_sha
        and transaction_plan.get("target_branch") == target_branch
        and transaction_plan.get("provider_name") == provider_name,
        "DURABLE_GIT_PLAN_AUTHORIZATION_BINDING_MISMATCH",
    )
    require(
        transaction_plan.get("single_use") is True
        and transaction_plan.get("automatic_retry_allowed") is False
        and transaction_plan.get("fallback_allowed") is False
        and transaction_plan.get("merge_allowed_by_plan") is False
        and transaction_plan.get("direct_main_update_allowed") is False
        and transaction_plan.get("apply_executed") is False,
        "DURABLE_GIT_PLAN_BOUNDARY_INVALID",
    )

    require(
        isinstance(candidate_files, Mapping)
        and set(candidate_files) == set(EXPECTED_PATHS)
        and all(isinstance(v, str) and v for v in candidate_files.values()),
        "DURABLE_GIT_CANDIDATE_FILE_SET_INVALID",
    )
    require(
        candidate_manifest_sha256(candidate_files)
        == expected_candidate_manifest_sha256,
        "DURABLE_GIT_CANDIDATE_MANIFEST_HASH_MISMATCH",
    )
    require(
        real_git_authorization.get("candidate_manifest_sha256")
        == expected_candidate_manifest_sha256
        and transaction_plan.get("candidate_manifest_sha256")
        == expected_candidate_manifest_sha256,
        "DURABLE_GIT_CANDIDATE_BINDING_MISMATCH",
    )

    file_plan = transaction_plan.get("files")
    require(
        isinstance(file_plan, Mapping)
        and set(file_plan) == set(EXPECTED_PATHS),
        "DURABLE_GIT_FILE_PLAN_INVALID",
    )
    for path in EXPECTED_PATHS:
        content = candidate_files[path].encode("utf-8")
        spec = file_plan[path]
        require(
            spec.get("mode") == "100644"
            and spec.get("content_sha256") == hashlib.sha256(content).hexdigest()
            and spec.get("git_blob_sha1") == _git_blob_sha1(content),
            "DURABLE_GIT_FILE_IDENTITY_MISMATCH:" + path,
        )

    require(
        type(receipt_store) is SyntheticWriteOnceReceiptStore,
        "DURABLE_GIT_REAL_RECEIPT_STORE_FORBIDDEN_IN_CI",
    )
    require(
        type(git_backend) is SyntheticGitBackend,
        "DURABLE_GIT_REAL_BACKEND_FORBIDDEN_IN_CI",
    )
    require(
        git_backend.refs.get("main") == main_sha,
        "DURABLE_GIT_BACKEND_MAIN_DRIFT",
    )
    require(
        target_branch not in git_backend.refs,
        "DURABLE_GIT_TARGET_BRANCH_ALREADY_EXISTS",
    )
    require(
        expected_transaction_plan_sha256 not in git_backend.consumed_tokens,
        "DURABLE_GIT_BACKEND_PLAN_ALREADY_CONSUMED",
    )

    return (
        str(main_sha),
        str(target_branch),
        str(provider_name),
        expected_real_git_authorization_sha256,
    )


def rehearse_durable_receipt_then_git(
    readiness: Mapping[str, Any],
    real_git_authorization: Mapping[str, Any],
    transaction_plan: Mapping[str, Any],
    candidate_files: Mapping[str, str],
    receipt_store: SyntheticWriteOnceReceiptStore,
    git_backend: SyntheticGitBackend,
    *,
    execution_id: str,
    expected_readiness_sha256: str,
    expected_real_git_authorization_sha256: str,
    expected_transaction_plan_sha256: str,
    expected_candidate_manifest_sha256: str,
) -> dict[str, Any]:
    main_sha, target_branch, provider_name, auth_hash = _preflight(
        readiness,
        real_git_authorization,
        transaction_plan,
        candidate_files,
        receipt_store,
        git_backend,
        expected_readiness_sha256=expected_readiness_sha256,
        expected_real_git_authorization_sha256=expected_real_git_authorization_sha256,
        expected_transaction_plan_sha256=expected_transaction_plan_sha256,
        expected_candidate_manifest_sha256=expected_candidate_manifest_sha256,
    )

    receipt = consume_execution_fence(
        real_git_authorization,
        receipt_store,
        execution_id=execution_id,
        expected_qualification_sha256=auth_hash,
        expected_current_main_sha=main_sha,
        expected_target_branch=target_branch,
    )
    persisted = validate_consumed_execution_fence(
        receipt_store,
        execution_id=execution_id,
        expected_receipt_sha256=receipt["receipt_sha256"],
        expected_qualification_sha256=auth_hash,
        expected_current_main_sha=main_sha,
        expected_target_branch=target_branch,
    )
    require(
        persisted.get("state") == "CONSUMED_BEFORE_GIT_MUTATION"
        and persisted.get("git_mutations_before_receipt") == 0,
        "DURABLE_GIT_RECEIPT_NOT_CLOSED_BEFORE_GIT",
    )

    git_result = rehearse_activation_git_transaction(
        transaction_plan,
        candidate_files,
        git_backend,
        expected_transaction_plan_sha256=expected_transaction_plan_sha256,
        expected_base_main_sha=main_sha,
        expected_candidate_manifest_sha256=expected_candidate_manifest_sha256,
    )
    require(
        git_result.get("validation_status") == "PASS"
        and git_result.get("synthetic_branch") == target_branch
        and git_result.get("blob_count") == 9
        and git_result.get("main_ref_unchanged") is True
        and git_result.get("branch_ref_created_last") is True,
        "DURABLE_GIT_SYNTHETIC_TRANSACTION_NOT_PASS",
    )

    return {
        "artifact": "RATE_DURABLE_RECEIPT_THEN_GIT_ORCHESTRATION_REHEARSAL_V1",
        "validation_status": "PASS",
        "execution_id": execution_id,
        "readiness_sha256": expected_readiness_sha256,
        "real_git_authorization_sha256": auth_hash,
        "transaction_plan_sha256": expected_transaction_plan_sha256,
        "candidate_manifest_sha256": expected_candidate_manifest_sha256,
        "current_main_sha": main_sha,
        "target_branch": target_branch,
        "intraday_provider_name": provider_name,
        "receipt_sha256": receipt["receipt_sha256"],
        "receipt_state": receipt["state"],
        "receipt_persisted_before_git": True,
        "git_mutations_before_receipt": 0,
        "synthetic_blob_count": 9,
        "synthetic_tree_sha": git_result["synthetic_tree_sha"],
        "synthetic_commit_sha": git_result["synthetic_commit_sha"],
        "synthetic_branch_created": True,
        "synthetic_branch_ref_created_last": True,
        "real_receipt_store_requests": 0,
        "real_git_operations": 0,
        "real_repository_writes": 0,
        "real_branch_created": False,
        "real_pull_request_created": False,
        "merge_performed": False,
        "live_provider_requests": 0,
        "external_intraday_dependency_resolved": False,
        "production_credit": 0,
        "cer081_credit": 0,
        "next_gate": "DRAFT_ACTIVATION_PR_EXECUTOR_REHEARSAL",
    }

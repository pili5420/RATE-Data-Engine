"""Final offline readiness gate before any explicit real Git activation transaction.

This gate binds all accepted pre-execution evidence to the same current main,
transaction plan, candidate manifest and activation branch. It performs no GitHub
request and consumes no durable receipt.
"""
from __future__ import annotations
from typing import Any, Mapping
from .intraday_activation_candidate_review import canonical_digest
from .intraday_real_git_execution_authorization import EXPECTED_BUDGET

class FinalRealGitReadinessError(RuntimeError):
    pass

def require(condition: bool, reason: str) -> None:
    if not condition:
        raise FinalRealGitReadinessError(reason)

def validate_final_real_git_execution_readiness(
    authority_store_readiness: Mapping[str,Any],
    real_git_authorization: Mapping[str,Any],
    transport_binding: Mapping[str,Any],
    http_rehearsal: Mapping[str,Any],
    *,
    expected_authority_store_readiness_sha256: str,
    expected_real_git_authorization_sha256: str,
    expected_transport_binding_sha256: str,
    expected_http_rehearsal_sha256: str,
    expected_current_main_sha: str,
) -> dict[str,Any]:
    require(canonical_digest(authority_store_readiness)==expected_authority_store_readiness_sha256,
            "FINAL_REAL_GIT_STORE_READINESS_HASH_MISMATCH")
    require(authority_store_readiness.get("artifact")=="RATE_REAL_GIT_EXECUTION_WITH_ACCEPTED_AUTHORITY_STORE_READINESS_V1"
            and authority_store_readiness.get("validation_status")=="PASS",
            "FINAL_REAL_GIT_STORE_READINESS_NOT_PASS")
    require(authority_store_readiness.get("current_main_sha")==expected_current_main_sha,
            "FINAL_REAL_GIT_STORE_MAIN_MISMATCH")
    require(authority_store_readiness.get("authority_store_provider_accepted") is True
            and authority_store_readiness.get("authority_store_provider_qualified") is True
            and authority_store_readiness.get("persist_receipt_before_first_git_mutation") is True
            and authority_store_readiness.get("write_once_receipt_required") is True
            and authority_store_readiness.get("receipt_retry_after_consumption_allowed") is False
            and authority_store_readiness.get("receipt_consumed") is False
            and authority_store_readiness.get("real_git_transaction_execution_allowed") is False,
            "FINAL_REAL_GIT_STORE_BOUNDARY_INVALID")

    require(canonical_digest(real_git_authorization)==expected_real_git_authorization_sha256,
            "FINAL_REAL_GIT_AUTH_HASH_MISMATCH")
    require(real_git_authorization.get("artifact")=="RATE_INTRADAY_REAL_GIT_TRANSACTION_EXECUTION_AUTHORIZATION_QUALIFICATION_V1"
            and real_git_authorization.get("validation_status")=="PASS"
            and real_git_authorization.get("authorization_valid") is True,
            "FINAL_REAL_GIT_AUTH_NOT_PASS")
    require(real_git_authorization.get("base_main_sha")==expected_current_main_sha,
            "FINAL_REAL_GIT_AUTH_MAIN_MISMATCH")
    target_branch=real_git_authorization.get("target_branch")
    require(target_branch==authority_store_readiness.get("target_branch"),
            "FINAL_REAL_GIT_BRANCH_MISMATCH")
    require(real_git_authorization.get("operation_budget")==EXPECTED_BUDGET
            and real_git_authorization.get("single_use") is True
            and real_git_authorization.get("retry_allowed") is False
            and real_git_authorization.get("draft_pull_request_required") is True
            and real_git_authorization.get("direct_main_update_allowed") is False
            and real_git_authorization.get("merge_allowed") is False
            and real_git_authorization.get("execution_performed") is False,
            "FINAL_REAL_GIT_AUTH_BOUNDARY_INVALID")

    require(canonical_digest(transport_binding)==expected_transport_binding_sha256,
            "FINAL_REAL_GIT_TRANSPORT_HASH_MISMATCH")
    require(transport_binding.get("artifact")=="RATE_REAL_GIT_DATA_TRANSPORT_BINDING_QUALIFICATION_V1"
            and transport_binding.get("validation_status")=="PASS",
            "FINAL_REAL_GIT_TRANSPORT_NOT_PASS")
    require(transport_binding.get("token_source")=="GITHUB_TOKEN"
            and transport_binding.get("workflow_permissions")=={"contents":"write"}
            and transport_binding.get("automatic_retry") is False
            and transport_binding.get("fallback") is False
            and transport_binding.get("real_github_requests")==0,
            "FINAL_REAL_GIT_TRANSPORT_BOUNDARY_INVALID")

    require(canonical_digest(http_rehearsal)==expected_http_rehearsal_sha256,
            "FINAL_REAL_GIT_HTTP_REHEARSAL_HASH_MISMATCH")
    require(http_rehearsal.get("artifact")=="RATE_REAL_GIT_DATA_HTTP_EXECUTOR_REHEARSAL_V1"
            and http_rehearsal.get("validation_status")=="PASS",
            "FINAL_REAL_GIT_HTTP_REHEARSAL_NOT_PASS")
    require(http_rehearsal.get("base_main_sha")==expected_current_main_sha,
            "FINAL_REAL_GIT_HTTP_MAIN_MISMATCH")
    require(http_rehearsal.get("target_branch")==target_branch,
            "FINAL_REAL_GIT_HTTP_BRANCH_MISMATCH")
    require(http_rehearsal.get("transaction_plan_sha256")==real_git_authorization.get("transaction_plan_sha256"),
            "FINAL_REAL_GIT_PLAN_MISMATCH")
    require(http_rehearsal.get("candidate_manifest_sha256")==real_git_authorization.get("candidate_manifest_sha256"),
            "FINAL_REAL_GIT_MANIFEST_MISMATCH")
    require(http_rehearsal.get("blob_count")==9
            and http_rehearsal.get("tree_count")==1
            and http_rehearsal.get("commit_count")==1
            and http_rehearsal.get("ref_create_count")==1
            and http_rehearsal.get("ref_create_retries")==0
            and http_rehearsal.get("branch_readback_verified") is True
            and http_rehearsal.get("main_ref_unchanged") is True
            and http_rehearsal.get("real_github_requests")==0
            and http_rehearsal.get("real_git_operations")==0
            and http_rehearsal.get("real_branch_created") is False,
            "FINAL_REAL_GIT_HTTP_BOUNDARY_INVALID")

    require(authority_store_readiness.get("real_git_operations")==0
            and real_git_authorization.get("real_git_operations")==0
            and authority_store_readiness.get("production_credit")==0
            and real_git_authorization.get("production_credit")==0
            and http_rehearsal.get("production_credit")==0,
            "FINAL_REAL_GIT_PREMATURE_EXECUTION_OR_CREDIT")

    return {
      "artifact":"RATE_FINAL_REAL_GIT_TRANSACTION_EXECUTION_READINESS_V1",
      "validation_status":"PASS",
      "readiness_disposition":"READY_FOR_CONTROL_CENTER_EXPLICIT_REAL_GIT_EXECUTION",
      "current_main_sha":expected_current_main_sha,
      "target_branch":target_branch,
      "transaction_plan_sha256":real_git_authorization["transaction_plan_sha256"],
      "candidate_manifest_sha256":real_git_authorization["candidate_manifest_sha256"],
      "authority_store_readiness_sha256":expected_authority_store_readiness_sha256,
      "real_git_authorization_sha256":expected_real_git_authorization_sha256,
      "transport_binding_sha256":expected_transport_binding_sha256,
      "http_rehearsal_sha256":expected_http_rehearsal_sha256,
      "receipt_consumed":False,
      "real_execution_allowed_by_validator":False,
      "real_github_requests":0,"real_git_operations":0,"real_branch_created":False,
      "production_credit":0,"cer081_credit":0,
      "next_gate":"CONTROL_CENTER_EXPLICIT_REAL_GIT_TRANSACTION_EXECUTION",
    }

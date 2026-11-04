"""Pure readiness gate for real Git execution with an accepted durable authority store.

This composes the real-Git transaction authorization with the role-specific Cloudflare
authority-store acceptance. It performs no receipt write and no Git operation.
"""
from __future__ import annotations

from typing import Any, Mapping

from .intraday_activation_candidate_review import canonical_digest
from .intraday_real_git_execution_authorization import EXPECTED_BUDGET


class RealGitAuthorityStoreReadinessError(RuntimeError):
    pass


def require(condition: bool, reason: str) -> None:
    if not condition:
        raise RealGitAuthorityStoreReadinessError(reason)


def validate_real_git_authority_store_readiness(
    authority_store_acceptance: Mapping[str,Any],
    real_git_authorization: Mapping[str,Any],
    *,
    expected_authority_store_acceptance_sha256: str,
    expected_real_git_authorization_sha256: str,
    expected_current_main_sha: str,
    expected_target_branch: str,
    expected_intraday_provider_name: str,
) -> dict[str,Any]:
    require(
        canonical_digest(authority_store_acceptance)
        == expected_authority_store_acceptance_sha256,
        "GIT_STORE_READY_ACCEPTANCE_HASH_MISMATCH",
    )
    require(
        authority_store_acceptance.get("artifact")
        =="RATE_CLOUDFLARE_AUTHORITY_STORE_PROVIDER_ACCEPTANCE_V1"
        and authority_store_acceptance.get("validation_status")=="PASS"
        and authority_store_acceptance.get("current_main_sha")==expected_current_main_sha,
        "GIT_STORE_READY_ACCEPTANCE_NOT_PASS",
    )
    require(
        authority_store_acceptance.get("provider")=="CLOUDFLARE_WORKERS_D1"
        and authority_store_acceptance.get("accepted_role")
        =="REAL_GIT_EXECUTION_CONSUMPTION_RECEIPT_STORE"
        and authority_store_acceptance.get("authority_store_provider_accepted") is True
        and authority_store_acceptance.get("authority_store_provider_qualified") is True,
        "GIT_STORE_READY_STORE_ROLE_INVALID",
    )
    require(
        authority_store_acceptance.get("intraday_market_data_provider_accepted") is False
        and authority_store_acceptance.get("real_git_transaction_execution_allowed") is False
        and authority_store_acceptance.get("production_activation_allowed") is False
        and authority_store_acceptance.get("external_intraday_dependency_resolved") is False
        and authority_store_acceptance.get("production_credit")==0
        and authority_store_acceptance.get("cer081_credit")==0,
        "GIT_STORE_READY_ACCEPTANCE_SCOPE_DRIFT",
    )

    require(
        canonical_digest(real_git_authorization)
        == expected_real_git_authorization_sha256,
        "GIT_STORE_READY_GIT_AUTH_HASH_MISMATCH",
    )
    require(
        real_git_authorization.get("artifact")
        =="RATE_INTRADAY_REAL_GIT_TRANSACTION_EXECUTION_AUTHORIZATION_QUALIFICATION_V1"
        and real_git_authorization.get("validation_status")=="PASS"
        and real_git_authorization.get("authorization_valid") is True,
        "GIT_STORE_READY_GIT_AUTH_NOT_PASS",
    )
    require(
        real_git_authorization.get("base_main_sha")==expected_current_main_sha
        and real_git_authorization.get("target_branch")==expected_target_branch
        and real_git_authorization.get("target_base")=="main",
        "GIT_STORE_READY_GIT_TARGET_BINDING_INVALID",
    )
    require(
        real_git_authorization.get("provider_name")==expected_intraday_provider_name,
        "GIT_STORE_READY_INTRADAY_PROVIDER_BINDING_INVALID",
    )
    require(
        real_git_authorization.get("operation_budget")==EXPECTED_BUDGET
        and real_git_authorization.get("single_use") is True
        and real_git_authorization.get("retry_allowed") is False
        and real_git_authorization.get("draft_pull_request_required") is True
        and real_git_authorization.get("direct_main_update_allowed") is False
        and real_git_authorization.get("merge_allowed") is False,
        "GIT_STORE_READY_GIT_OPERATION_BOUNDARY_INVALID",
    )
    require(
        real_git_authorization.get("execution_performed") is False
        and real_git_authorization.get("real_git_operations")==0
        and real_git_authorization.get("live_provider_requests")==0
        and real_git_authorization.get("external_dependency_resolved") is False
        and real_git_authorization.get("registry_activation_allowed") is False
        and real_git_authorization.get("production_credit")==0
        and real_git_authorization.get("cer081_credit")==0,
        "GIT_STORE_READY_GIT_PREMATURE_STATE",
    )

    return {
        "artifact":"RATE_REAL_GIT_EXECUTION_WITH_ACCEPTED_AUTHORITY_STORE_READINESS_V1",
        "validation_status":"PASS",
        "current_main_sha":expected_current_main_sha,
        "target_branch":expected_target_branch,
        "intraday_provider_name":expected_intraday_provider_name,
        "authority_store_provider":"CLOUDFLARE_WORKERS_D1",
        "authority_store_role":"REAL_GIT_EXECUTION_CONSUMPTION_RECEIPT_STORE",
        "authority_store_provider_accepted":True,
        "authority_store_provider_qualified":True,
        "operation_budget":dict(EXPECTED_BUDGET),
        "consumption_receipt_artifact":
            "RATE_INTRADAY_REAL_GIT_EXECUTION_CONSUMPTION_RECEIPT_V1",
        "consumption_receipt_state":"CONSUMED_BEFORE_GIT_MUTATION",
        "persist_receipt_before_first_git_mutation":True,
        "write_once_receipt_required":True,
        "receipt_retry_after_consumption_allowed":False,
        "readiness_only":True,
        "real_git_transaction_execution_allowed":False,
        "receipt_consumed":False,
        "real_git_operations":0,
        "live_provider_requests":0,
        "external_intraday_dependency_resolved":False,
        "production_credit":0,
        "cer081_credit":0,
        "next_gate":"SEPARATE_REAL_GIT_EXECUTOR_WITH_DURABLE_RECEIPT_AUTHORIZATION",
    }

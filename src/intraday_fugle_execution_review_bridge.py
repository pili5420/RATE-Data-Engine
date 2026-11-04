"""Bridge a validated Fugle execution result into the existing live-review package builder."""
from __future__ import annotations

from typing import Any, Mapping

from .intraday_live_review_package import build_live_review_package


class FugleExecutionReviewBridgeError(RuntimeError):
    pass


def require(condition: bool, reason: str) -> None:
    if not condition:
        raise FugleExecutionReviewBridgeError(reason)


def build_review_package_from_execution(
    execution_result: Mapping[str, Any],
    *,
    engineering_source_sha: str,
    trigger_commit_sha: str,
    workflow_run_id: int,
    workflow_job_id: int,
    workflow_attempt: int,
    rerun_count: int,
    job_retry_count: int,
    secret_scan_status: str,
) -> dict[str, Any]:
    require(isinstance(execution_result, Mapping),
            "FUGLE_REVIEW_BRIDGE_EXECUTION_RESULT_INVALID")
    require(
        execution_result.get("artifact") == "RATE_FUGLE_SINGLE_LIVE_EXECUTION_RESULT_V1"
        and execution_result.get("validation_status") == "PASS",
        "FUGLE_REVIEW_BRIDGE_EXECUTION_RESULT_NOT_PASS",
    )
    require(execution_result.get("provider") == "Fugle",
            "FUGLE_REVIEW_BRIDGE_PROVIDER_INVALID")
    require(execution_result.get("fence_readback_verified") is True
            and execution_result.get("single_use_consumed") is True,
            "FUGLE_REVIEW_BRIDGE_FENCE_NOT_CLOSED")
    require(execution_result.get("github_fence_requests") == 3,
            "FUGLE_REVIEW_BRIDGE_FENCE_REQUEST_COUNT_INVALID")
    require(execution_result.get("provider_network_requests") == 30,
            "FUGLE_REVIEW_BRIDGE_PROVIDER_REQUEST_COUNT_INVALID")
    require(execution_result.get("automatic_retries") == 0
            and execution_result.get("fallback_used") is False
            and execution_result.get("redirects_followed") == 0,
            "FUGLE_REVIEW_BRIDGE_NETWORK_BOUNDARY_INVALID")
    require(execution_result.get("production_activation_allowed") is False
            and execution_result.get("external_dependency_resolved") is False
            and execution_result.get("production_credit") == 0
            and execution_result.get("cer081_credit") == 0,
            "FUGLE_REVIEW_BRIDGE_PREMATURE_PRODUCTION_STATE")

    provider_result=execution_result.get("provider_result")
    require(isinstance(provider_result, Mapping),
            "FUGLE_REVIEW_BRIDGE_PROVIDER_RESULT_MISSING")
    require(provider_result.get("technical_validation_status") == "PASS",
            "FUGLE_REVIEW_BRIDGE_PROVIDER_RESULT_NOT_PASS")
    require(provider_result.get("network_requests") == 30,
            "FUGLE_REVIEW_BRIDGE_PROVIDER_RESULT_REQUEST_COUNT_INVALID")
    require(provider_result.get("trading_date") == execution_result.get("trading_date")
            and provider_result.get("cadence") == execution_result.get("cadence"),
            "FUGLE_REVIEW_BRIDGE_SCOPE_MISMATCH")

    package=build_live_review_package(
        provider_result,
        engineering_source_sha=engineering_source_sha,
        trigger_commit_sha=trigger_commit_sha,
        workflow_run_id=workflow_run_id,
        workflow_job_id=workflow_job_id,
        provider_name="Fugle",
        trading_date=execution_result["trading_date"],
        cadence=execution_result["cadence"],
        workflow_attempt=workflow_attempt,
        rerun_count=rerun_count,
        job_retry_count=job_retry_count,
        single_use_consumed=True,
        secret_scan_status=secret_scan_status,
    )
    package["execution_binding"]={
        "artifact":"RATE_FUGLE_SINGLE_LIVE_EXECUTION_RESULT_V1",
        "authorization_review_sha256":execution_result["authorization_review_sha256"],
        "authorization_sha256":execution_result["authorization_sha256"],
        "current_main_sha":execution_result["current_main_sha"],
        "fence_marker_ref":execution_result["fence_marker_ref"],
        "fence_marker_target_sha":execution_result["fence_marker_target_sha"],
        "fence_readback_verified":True,
        "single_use_consumed":True,
        "github_fence_requests":3,
        "provider_network_requests":30,
    }
    return package

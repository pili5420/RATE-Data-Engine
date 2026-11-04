"""Synthetic orchestration of fence-first then one Fugle qualification execution."""
from __future__ import annotations

from typing import Any, Mapping

from .intraday_fugle_live_consumption_fence import (
    SyntheticWriteOnceFenceStore,
    canonical_digest,
    consume_fugle_single_live_fence,
)
from .intraday_fugle_live_executor_rehearsal import build_fugle_live_executor_rehearsal


class FugleLiveExecutorOrchestrationError(RuntimeError):
    pass


def require(condition: bool, reason: str) -> None:
    if not condition:
        raise FugleLiveExecutorOrchestrationError(reason)


class SyntheticFugleExecutorBackend:
    backend="SYNTHETIC_FUGLE_EXECUTOR_BACKEND"

    def __init__(self, *, expected_requests: int=30):
        self.expected_requests=expected_requests
        self.credential_reads=0
        self.network_requests=0
        self.retry_count=0
        self.redirect_count=0
        self.fallback_used=False

    def execute_after_fence(self, *, request_budget: int) -> dict[str, Any]:
        require(request_budget==30, "FUGLE_ORCH_REQUEST_BUDGET_INVALID")
        self.credential_reads += 1
        self.network_requests += self.expected_requests
        return {
            "technical_validation_status":"PASS",
            "market_coverage":"30/30",
            "network_requests":self.network_requests,
            "credential_reads":self.credential_reads,
            "automatic_retries":self.retry_count,
            "http_redirects_followed":self.redirect_count,
            "fallback_used":self.fallback_used,
        }


def rehearse_fugle_fence_then_execute(
    authorization_review: Mapping[str, Any],
    fence_store: SyntheticWriteOnceFenceStore,
    backend: SyntheticFugleExecutorBackend,
    *,
    expected_authorization_review_sha256: str,
    expected_main_sha: str,
    trading_date: str,
    output_name: str,
) -> dict[str, Any]:
    require(type(backend) is SyntheticFugleExecutorBackend,
            "FUGLE_ORCH_REAL_BACKEND_FORBIDDEN_IN_CI")

    rehearsal=build_fugle_live_executor_rehearsal(
        authorization_review,
        expected_main_sha=expected_main_sha,
        expected_authorization_sha256=authorization_review["authorization_sha256"],
        trading_date=trading_date,
        output_name=output_name,
    )
    require(rehearsal.get("validation_status")=="PASS",
            "FUGLE_ORCH_EXECUTOR_REHEARSAL_NOT_PASS")
    require(rehearsal.get("network_requests_by_rehearsal")==0
            and rehearsal.get("credential_access_by_rehearsal")==0,
            "FUGLE_ORCH_REHEARSAL_SIDE_EFFECT_INVALID")

    fence=consume_fugle_single_live_fence(
        authorization_review,
        fence_store,
        expected_authorization_review_sha256=expected_authorization_review_sha256,
        expected_main_sha=expected_main_sha,
    )
    require(fence.get("validation_status")=="PASS"
            and fence.get("readback_verified") is True,
            "FUGLE_ORCH_FENCE_NOT_CLOSED")
    require(fence.get("credential_access_before_receipt")==0
            and fence.get("provider_requests_before_receipt")==0,
            "FUGLE_ORCH_PRE_FENCE_IO_DETECTED")

    result=backend.execute_after_fence(request_budget=30)
    require(result.get("technical_validation_status")=="PASS",
            "FUGLE_ORCH_SYNTHETIC_RESULT_NOT_PASS")
    require(result.get("network_requests")==30,
            "FUGLE_ORCH_REQUEST_COUNT_INVALID")
    require(result.get("credential_reads")==1,
            "FUGLE_ORCH_CREDENTIAL_READ_COUNT_INVALID")
    require(result.get("automatic_retries")==0
            and result.get("http_redirects_followed")==0
            and result.get("fallback_used") is False,
            "FUGLE_ORCH_NETWORK_POLICY_VIOLATION")

    return {
        "artifact":"RATE_FUGLE_SINGLE_LIVE_FENCE_THEN_EXECUTOR_REHEARSAL_V1",
        "validation_status":"PASS",
        "authorization_review_sha256":expected_authorization_review_sha256,
        "authorization_sha256":authorization_review["authorization_sha256"],
        "main_sha":expected_main_sha,
        "trading_date":trading_date,
        "cadence":authorization_review["cadence"],
        "fence_receipt_sha256":fence["receipt_sha256"],
        "fence_persisted_and_readback_before_credential":True,
        "credential_reads_after_fence":1,
        "provider_requests_after_fence":30,
        "automatic_retries":0,
        "http_redirects_followed":0,
        "fallback_used":False,
        "synthetic_backend_used":True,
        "real_provider_requests":0,
        "real_credential_reads":0,
        "real_store_writes":0,
        "production_activation_allowed":False,
        "external_dependency_resolved":False,
        "production_credit":0,
        "cer081_credit":0,
        "next_gate":"REAL_FUGLE_SINGLE_LIVE_EXECUTOR_IMPLEMENTATION"
    }

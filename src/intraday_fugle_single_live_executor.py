"""Production-shaped executor for one authorized Fugle single-live qualification.

The executor enforces: authorization review -> durable GitHub consumption marker ->
provider credential use -> exact 30-request Fugle qualification.

CI injects fake HTTPS transports for both GitHub and Fugle. No real request is made.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Callable, Mapping

from .intraday_fugle_github_fence_adapter import persist_consumption_marker
from .intraday_fugle_github_fence_transport import FugleGitHubFenceTransport
from .intraday_fugle_live_consumption_fence import canonical_digest
from .provider_fugle_intraday_candidate import qualify


class FugleSingleLiveExecutorError(RuntimeError):
    pass


def require(condition: bool, reason: str) -> None:
    if not condition:
        raise FugleSingleLiveExecutorError(reason)


def execute_authorized_fugle_single_live(
    authorization_review: Mapping[str, Any],
    binding: Mapping[str, Any],
    *,
    expected_authorization_review_sha256: str,
    github_token: str,
    fugle_api_key: str | None = None,
    fugle_credential_loader: Callable[[], str] | None = None,
    trading_date: str,
    now_utc: datetime,
    github_transport_factory: Callable[..., FugleGitHubFenceTransport] = FugleGitHubFenceTransport,
    fugle_connection_factory: Callable[..., Any],
) -> dict[str, Any]:
    require(isinstance(authorization_review, Mapping),
            "FUGLE_EXEC_AUTH_REVIEW_INVALID")
    require(canonical_digest(authorization_review) == expected_authorization_review_sha256,
            "FUGLE_EXEC_AUTH_REVIEW_HASH_MISMATCH")
    require(
        authorization_review.get("artifact")
        == "RATE_FUGLE_SINGLE_LIVE_QUALIFICATION_AUTHORIZATION_QUALIFICATION_V1"
        and authorization_review.get("validation_status") == "PASS",
        "FUGLE_EXEC_AUTH_REVIEW_NOT_PASS",
    )
    require(authorization_review.get("provider") == "Fugle",
            "FUGLE_EXEC_PROVIDER_INVALID")
    require(authorization_review.get("single_use") is True
            and authorization_review.get("execution_consumed") is False,
            "FUGLE_EXEC_SINGLE_USE_BOUNDARY_INVALID")
    require(authorization_review.get("request_budget") == 30,
            "FUGLE_EXEC_REQUEST_BUDGET_INVALID")
    require(authorization_review.get("automatic_retry_allowed") is False
            and authorization_review.get("fallback_allowed") is False
            and authorization_review.get("redirect_allowed") is False,
            "FUGLE_EXEC_NETWORK_BOUNDARY_INVALID")
    require(authorization_review.get("credential_store") == "GITHUB_ACTIONS_SECRET"
            and authorization_review.get("credential_secret_name") == "FUGLE_API_KEY",
            "FUGLE_EXEC_CREDENTIAL_BOUNDARY_INVALID")
    require(isinstance(github_token, str) and github_token,
            "FUGLE_EXEC_GITHUB_TOKEN_MISSING")
    require((fugle_credential_loader is None and isinstance(fugle_api_key, str) and bool(fugle_api_key))
            or (callable(fugle_credential_loader) and fugle_api_key is None),
            "FUGLE_EXEC_FUGLE_API_KEY_MISSING")

    main_sha=authorization_review.get("current_main_sha")
    auth_sha=authorization_review.get("authorization_sha256")
    cadence=authorization_review.get("cadence")
    require(isinstance(main_sha,str) and len(main_sha)==40,
            "FUGLE_EXEC_MAIN_SHA_INVALID")
    require(isinstance(auth_sha,str) and len(auth_sha)==64,
            "FUGLE_EXEC_AUTH_SHA_INVALID")
    require(cadence in {"09:30","12:00"},
            "FUGLE_EXEC_CADENCE_INVALID")

    # Fence first. If this step cannot prove durable consumption, provider access is forbidden.
    transport=github_transport_factory(github_token=github_token)
    fence_result=persist_consumption_marker(
        transport,
        authorization_sha256=auth_sha,
        main_sha=main_sha,
    )
    require(fence_result.get("validation_status")=="PASS"
            and fence_result.get("readback_verified") is True
            and fence_result.get("executor_ownership_verified") is True,
            "FUGLE_EXEC_FENCE_NOT_CLOSED")

    # A loader may access a credential only after this invocation proves ownership.
    if fugle_credential_loader is not None:
        fugle_api_key = fugle_credential_loader()
    require(isinstance(fugle_api_key, str) and bool(fugle_api_key),
            "FUGLE_EXEC_FUGLE_API_KEY_MISSING")
    result=qualify(
        fugle_api_key,
        binding,
        trading_date=trading_date,
        cadence=cadence,
        now_utc=now_utc,
        connection_factory=fugle_connection_factory,
    )
    require(result.get("technical_validation_status")=="PASS",
            "FUGLE_EXEC_PROVIDER_RESULT_NOT_PASS")
    require(result.get("network_requests")==30,
            "FUGLE_EXEC_PROVIDER_REQUEST_COUNT_INVALID")
    require(result.get("automatic_retries")==0
            and result.get("http_redirects_followed")==0
            and result.get("fallback_used") is False,
            "FUGLE_EXEC_PROVIDER_NETWORK_POLICY_INVALID")
    require(result.get("production_eligible") is False
            and result.get("registry_activation_allowed") is False
            and result.get("external_dependency_resolved") is False,
            "FUGLE_EXEC_PREMATURE_PRODUCTION_STATE")

    return {
        "artifact":"RATE_FUGLE_SINGLE_LIVE_EXECUTION_RESULT_V1",
        "validation_status":"PASS",
        "authorization_review_sha256":expected_authorization_review_sha256,
        "authorization_sha256":auth_sha,
        "current_main_sha":main_sha,
        "provider":"Fugle",
        "trading_date":trading_date,
        "cadence":cadence,
        "fence_marker_ref":fence_result["marker_ref"],
        "fence_marker_target_sha":fence_result["marker_target_sha"],
        "fence_readback_verified":True,
        "executor_ownership_verified":True,
        "single_use_consumed":True,
        "github_fence_requests":fence_result["github_requests"],
        "provider_network_requests":30,
        "provider_result":result,
        "automatic_retries":0,
        "fallback_used":False,
        "redirects_followed":0,
        "production_activation_allowed":False,
        "external_dependency_resolved":False,
        "production_credit":0,
        "cer081_credit":0,
        "next_gate":"RATE_INTRADAY_SINGLE_LIVE_QUALIFICATION_REVIEW_V1"
    }

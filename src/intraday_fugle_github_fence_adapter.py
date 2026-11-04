"""Fence adapter using the bounded Fugle GitHub-ref transport."""
from __future__ import annotations

from typing import Any, Mapping

from .intraday_fugle_github_fence_transport import (
    FugleGitHubFenceTransport,
    FugleGitHubFenceTransportError,
    ref_name_for,
)


class FugleGitHubFenceAdapterError(RuntimeError):
    pass


def require(condition: bool, reason: str) -> None:
    if not condition:
        raise FugleGitHubFenceAdapterError(reason)


def persist_consumption_marker(
    transport: FugleGitHubFenceTransport,
    *,
    authorization_sha256: str,
    main_sha: str,
) -> dict[str,Any]:
    require(type(transport) is FugleGitHubFenceTransport,
            "FUGLE_GH_ADAPTER_TRANSPORT_INVALID")
    existing=transport.read_marker(authorization_sha256)
    if existing is not None:
        require(existing.get("sha")==main_sha,
                "FUGLE_GH_ADAPTER_EXISTING_TARGET_CONFLICT")
        raise FugleGitHubFenceAdapterError("FUGLE_GH_ADAPTER_ALREADY_CONSUMED")

    try:
        created=transport.create_marker(authorization_sha256,main_sha)
    except FugleGitHubFenceTransportError:
        # Ambiguous POST outcomes are never retried. Resolve by exact marker readback.
        persisted=transport.read_marker(authorization_sha256)
        require(persisted is not None,
                "FUGLE_GH_ADAPTER_AMBIGUOUS_CREATE_UNRESOLVED")
        require(persisted.get("sha")==main_sha,
                "FUGLE_GH_ADAPTER_AMBIGUOUS_TARGET_CONFLICT")
        outcome="AMBIGUOUS_CREATE_CONFIRMED_BY_READBACK"
    else:
        require(created.get("ref")==ref_name_for(authorization_sha256)
                and created.get("sha")==main_sha,
                "FUGLE_GH_ADAPTER_CREATE_RESULT_MISMATCH")
        persisted=transport.read_marker(authorization_sha256)
        require(persisted is not None and persisted.get("sha")==main_sha,
                "FUGLE_GH_ADAPTER_READBACK_MISMATCH")
        outcome="CREATED_AND_READBACK_VERIFIED"

    require(transport.request_count in {3},
            "FUGLE_GH_ADAPTER_REQUEST_BUDGET_INVALID")
    return {
        "artifact":"RATE_FUGLE_GITHUB_REF_CONSUMPTION_MARKER_RESULT_V1",
        "validation_status":"PASS",
        "outcome":outcome,
        "marker_ref":ref_name_for(authorization_sha256),
        "marker_target_sha":main_sha,
        "authorization_sha256":authorization_sha256,
        "github_requests":transport.request_count,
        "create_retries":0,
        "update_requests":0,
        "delete_requests":0,
        "list_requests":0,
        "main_ref_updates":0,
        "readback_verified":True,
        "credential_access_after_marker_allowed":True,
        "provider_requests_after_marker_allowed":True,
        "production_activation_allowed":False,
        "external_dependency_resolved":False,
        "production_credit":0,
        "cer081_credit":0,
    }

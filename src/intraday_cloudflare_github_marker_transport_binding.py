"""Offline qualification for the real GitHub marker transport binding.

This validator fixes the future workflow credential/permission/host/path boundary.
It performs no GitHub request.
"""
from __future__ import annotations

from typing import Any, Mapping


class GitHubMarkerTransportBindingError(RuntimeError):
    pass


def require(condition: bool, reason: str) -> None:
    if not condition:
        raise GitHubMarkerTransportBindingError(reason)


def validate_github_marker_transport_binding(policy: Mapping[str, Any]) -> dict[str, Any]:
    require(isinstance(policy, Mapping), "GH_MARKER_TRANSPORT_POLICY_INVALID")
    require(
        policy.get("artifact")
        == "RATE_CLOUDFLARE_GITHUB_MARKER_TRANSPORT_BINDING_V1",
        "GH_MARKER_TRANSPORT_ARTIFACT_INVALID",
    )
    require(policy.get("repository") == "pili5420/RATE-Data-Engine",
            "GH_MARKER_TRANSPORT_REPOSITORY_INVALID")
    require(policy.get("token_source") == "GITHUB_TOKEN",
            "GH_MARKER_TRANSPORT_TOKEN_SOURCE_INVALID")
    require(policy.get("custom_pat_secret") is None,
            "GH_MARKER_TRANSPORT_PAT_FORBIDDEN")

    perms = policy.get("workflow_permissions")
    require(isinstance(perms, Mapping), "GH_MARKER_TRANSPORT_PERMISSIONS_MISSING")
    require(perms == {"contents": "write"},
            "GH_MARKER_TRANSPORT_PERMISSIONS_NOT_MINIMAL")

    require(policy.get("api_host") == "api.github.com",
            "GH_MARKER_TRANSPORT_HOST_INVALID")
    require(policy.get("scheme") == "https",
            "GH_MARKER_TRANSPORT_SCHEME_INVALID")
    require(policy.get("tls_hostname_verification") is True
            and policy.get("tls_certificate_verification") is True,
            "GH_MARKER_TRANSPORT_TLS_INVALID")
    require(policy.get("redirect_following") is False,
            "GH_MARKER_TRANSPORT_REDIRECT_FORBIDDEN")
    require(policy.get("automatic_retry") is False,
            "GH_MARKER_TRANSPORT_RETRY_FORBIDDEN")
    require(policy.get("fallback") is False,
            "GH_MARKER_TRANSPORT_FALLBACK_FORBIDDEN")

    allowed = policy.get("allowed_requests")
    require(
        allowed == [
            {
                "method": "GET",
                "path_template":
                    "/repos/pili5420/RATE-Data-Engine/git/ref/tags/"
                    "rate-v11-qualification-consumed/cloudflare-d1-{hash_prefix}",
            },
            {
                "method": "POST",
                "path": "/repos/pili5420/RATE-Data-Engine/git/refs",
            },
        ],
        "GH_MARKER_TRANSPORT_REQUEST_SURFACE_INVALID",
    )
    require(policy.get("patch_ref_allowed") is False
            and policy.get("delete_ref_allowed") is False
            and policy.get("list_refs_allowed") is False
            and policy.get("main_ref_update_allowed") is False,
            "GH_MARKER_TRANSPORT_FORBIDDEN_REF_ACTION")

    headers = policy.get("required_headers")
    require(isinstance(headers, Mapping), "GH_MARKER_TRANSPORT_HEADERS_MISSING")
    require(headers.get("Accept") == "application/vnd.github+json",
            "GH_MARKER_TRANSPORT_ACCEPT_HEADER_INVALID")
    require(headers.get("X-GitHub-Api-Version") == "2022-11-28",
            "GH_MARKER_TRANSPORT_API_VERSION_INVALID")
    require(headers.get("Authorization") == "Bearer ${GITHUB_TOKEN}",
            "GH_MARKER_TRANSPORT_AUTH_HEADER_INVALID")

    require(policy.get("real_github_requests") == 0
            and policy.get("real_git_ref_created") is False
            and policy.get("real_cloudflare_requests") == 0,
            "GH_MARKER_TRANSPORT_PREMATURE_EXECUTION")

    return {
        "artifact": "RATE_CLOUDFLARE_GITHUB_MARKER_TRANSPORT_BINDING_QUALIFICATION_V1",
        "validation_status": "PASS",
        "repository": "pili5420/RATE-Data-Engine",
        "token_source": "GITHUB_TOKEN",
        "workflow_permissions": {"contents": "write"},
        "api_host": "api.github.com",
        "scheme": "https",
        "allowed_methods": ["GET", "POST"],
        "redirect_following": False,
        "automatic_retry": False,
        "fallback": False,
        "real_github_requests": 0,
        "real_git_ref_created": False,
        "next_gate": "EXPLICIT_REAL_GITHUB_MARKER_EXECUTION",
    }

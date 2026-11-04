"""Offline qualification for the real GitHub Draft-PR transport boundary.

This validator performs no GitHub request. It fixes the exact credential, permission,
host, request surface and recursive-workflow assumptions for a future one-shot Draft
activation PR creation.
"""
from __future__ import annotations
from typing import Any, Mapping

class DraftPRTransportBindingError(RuntimeError):
    pass

def require(condition: bool, reason: str) -> None:
    if not condition:
        raise DraftPRTransportBindingError(reason)

EXPECTED_REQUESTS = [
    {
        "method": "GET",
        "path_template":
            "/repos/pili5420/RATE-Data-Engine/pulls"
            "?state=open&head=pili5420:{head}&base=main",
    },
    {
        "method": "POST",
        "path": "/repos/pili5420/RATE-Data-Engine/pulls",
        "required_body": {
            "head": "{head}",
            "base": "main",
            "draft": True,
        },
    },
]

def validate_real_draft_pr_transport_binding(policy: Mapping[str, Any]) -> dict[str, Any]:
    require(isinstance(policy, Mapping), "REAL_DRAFT_PR_TRANSPORT_POLICY_INVALID")
    require(
        policy.get("artifact")
        == "RATE_REAL_DRAFT_ACTIVATION_PR_TRANSPORT_BINDING_V1",
        "REAL_DRAFT_PR_TRANSPORT_ARTIFACT_INVALID",
    )
    require(
        policy.get("repository") == "pili5420/RATE-Data-Engine",
        "REAL_DRAFT_PR_TRANSPORT_REPOSITORY_INVALID",
    )
    require(policy.get("token_source") == "GITHUB_TOKEN",
            "REAL_DRAFT_PR_TRANSPORT_TOKEN_SOURCE_INVALID")
    require(policy.get("custom_pat_secret") is None,
            "REAL_DRAFT_PR_TRANSPORT_PAT_FORBIDDEN")
    require(
        policy.get("workflow_permissions")
        == {"contents": "read", "pull-requests": "write"},
        "REAL_DRAFT_PR_TRANSPORT_PERMISSIONS_NOT_MINIMAL",
    )
    require(
        policy.get("repo_actions_pr_creation_policy")
        == "EXTERNALLY_VERIFIED_ENABLED",
        "REAL_DRAFT_PR_TRANSPORT_REPO_POLICY_UNPROVEN",
    )

    require(policy.get("scheme") == "https"
            and policy.get("api_host") == "api.github.com",
            "REAL_DRAFT_PR_TRANSPORT_DESTINATION_INVALID")
    require(policy.get("tls_hostname_verification") is True
            and policy.get("tls_certificate_verification") is True,
            "REAL_DRAFT_PR_TRANSPORT_TLS_INVALID")
    require(policy.get("redirect_following") is False,
            "REAL_DRAFT_PR_TRANSPORT_REDIRECT_FORBIDDEN")
    require(policy.get("automatic_retry") is False,
            "REAL_DRAFT_PR_TRANSPORT_RETRY_FORBIDDEN")
    require(policy.get("fallback") is False,
            "REAL_DRAFT_PR_TRANSPORT_FALLBACK_FORBIDDEN")

    require(
        policy.get("allowed_requests") == EXPECTED_REQUESTS,
        "REAL_DRAFT_PR_TRANSPORT_REQUEST_SURFACE_INVALID",
    )
    require(policy.get("patch_pull_request_allowed") is False
            and policy.get("ready_for_review_allowed") is False
            and policy.get("merge_endpoint_allowed") is False
            and policy.get("auto_merge_allowed") is False
            and policy.get("merge_queue_allowed") is False
            and policy.get("issue_comment_write_allowed") is False,
            "REAL_DRAFT_PR_TRANSPORT_FORBIDDEN_ACTION")

    headers = policy.get("required_headers")
    require(isinstance(headers, Mapping), "REAL_DRAFT_PR_TRANSPORT_HEADERS_MISSING")
    require(headers.get("Accept") == "application/vnd.github+json",
            "REAL_DRAFT_PR_TRANSPORT_ACCEPT_HEADER_INVALID")
    require(headers.get("X-GitHub-Api-Version") == "2022-11-28",
            "REAL_DRAFT_PR_TRANSPORT_API_VERSION_INVALID")
    require(headers.get("Authorization") == "Bearer ${GITHUB_TOKEN}",
            "REAL_DRAFT_PR_TRANSPORT_AUTH_HEADER_INVALID")

    require(policy.get("auto_ci_trigger_expected") is False
            and policy.get("manual_workflow_approval_may_be_required") is True,
            "REAL_DRAFT_PR_TRANSPORT_RECURSIVE_WORKFLOW_ASSUMPTION_INVALID")

    require(policy.get("real_github_requests") == 0
            and policy.get("real_pull_request_created") is False
            and policy.get("merge_performed") is False,
            "REAL_DRAFT_PR_TRANSPORT_PREMATURE_EXECUTION")

    return {
        "artifact": "RATE_REAL_DRAFT_ACTIVATION_PR_TRANSPORT_BINDING_QUALIFICATION_V1",
        "validation_status": "PASS",
        "repository": "pili5420/RATE-Data-Engine",
        "token_source": "GITHUB_TOKEN",
        "workflow_permissions": {
            "contents": "read",
            "pull-requests": "write",
        },
        "api_host": "api.github.com",
        "scheme": "https",
        "allowed_methods": ["GET", "POST"],
        "draft_required": True,
        "base": "main",
        "redirect_following": False,
        "automatic_retry": False,
        "fallback": False,
        "auto_ci_trigger_expected": False,
        "manual_workflow_approval_may_be_required": True,
        "real_github_requests": 0,
        "real_pull_request_created": False,
        "next_gate": "EXPLICIT_REAL_DRAFT_PR_TRANSPORT_EXECUTION",
    }

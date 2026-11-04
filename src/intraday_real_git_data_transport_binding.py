"""Offline qualification for the GitHub Git-Data transport used by a future real activation transaction."""
from __future__ import annotations
from typing import Any, Mapping

class RealGitDataTransportBindingError(RuntimeError):
    pass

def require(condition: bool, reason: str) -> None:
    if not condition:
        raise RealGitDataTransportBindingError(reason)

EXPECTED_REQUESTS = [
    {"method":"GET","path":"/repos/pili5420/RATE-Data-Engine/git/ref/heads/main"},
    {"method":"GET","path_template":"/repos/pili5420/RATE-Data-Engine/git/commits/{base_main_sha}"},
    {"method":"GET","path_template":"/repos/pili5420/RATE-Data-Engine/git/ref/heads/{activation_branch}"},
    {"method":"POST","path":"/repos/pili5420/RATE-Data-Engine/git/blobs","max_count":9},
    {"method":"POST","path":"/repos/pili5420/RATE-Data-Engine/git/trees","max_count":1},
    {"method":"POST","path":"/repos/pili5420/RATE-Data-Engine/git/commits","max_count":1},
    {"method":"POST","path":"/repos/pili5420/RATE-Data-Engine/git/refs","max_count":1},
]

def validate_real_git_data_transport_binding(policy: Mapping[str,Any]) -> dict[str,Any]:
    require(isinstance(policy,Mapping),"REAL_GIT_TRANSPORT_POLICY_INVALID")
    require(policy.get("artifact")=="RATE_REAL_GIT_DATA_TRANSPORT_BINDING_V1","REAL_GIT_TRANSPORT_ARTIFACT_INVALID")
    require(policy.get("repository")=="pili5420/RATE-Data-Engine","REAL_GIT_TRANSPORT_REPOSITORY_INVALID")
    require(policy.get("token_source")=="GITHUB_TOKEN","REAL_GIT_TRANSPORT_TOKEN_SOURCE_INVALID")
    require(policy.get("custom_pat_secret") is None,"REAL_GIT_TRANSPORT_PAT_FORBIDDEN")
    require(policy.get("workflow_permissions")=={"contents":"write"},"REAL_GIT_TRANSPORT_PERMISSIONS_NOT_MINIMAL")
    require(policy.get("repo_actions_contents_write_policy")=="EXTERNALLY_VERIFIED_ENABLED","REAL_GIT_TRANSPORT_REPO_POLICY_UNPROVEN")
    require(policy.get("scheme")=="https" and policy.get("api_host")=="api.github.com","REAL_GIT_TRANSPORT_DESTINATION_INVALID")
    require(policy.get("tls_hostname_verification") is True and policy.get("tls_certificate_verification") is True,"REAL_GIT_TRANSPORT_TLS_INVALID")
    require(policy.get("redirect_following") is False,"REAL_GIT_TRANSPORT_REDIRECT_FORBIDDEN")
    require(policy.get("automatic_retry") is False,"REAL_GIT_TRANSPORT_RETRY_FORBIDDEN")
    require(policy.get("fallback") is False,"REAL_GIT_TRANSPORT_FALLBACK_FORBIDDEN")
    require(policy.get("allowed_requests")==EXPECTED_REQUESTS,"REAL_GIT_TRANSPORT_REQUEST_SURFACE_INVALID")
    require(policy.get("patch_ref_allowed") is False
            and policy.get("delete_ref_allowed") is False
            and policy.get("merge_endpoint_allowed") is False
            and policy.get("pull_request_endpoint_allowed") is False
            and policy.get("main_ref_update_allowed") is False,
            "REAL_GIT_TRANSPORT_FORBIDDEN_ACTION")
    headers=policy.get("required_headers")
    require(isinstance(headers,Mapping),"REAL_GIT_TRANSPORT_HEADERS_MISSING")
    require(headers.get("Accept")=="application/vnd.github+json","REAL_GIT_TRANSPORT_ACCEPT_HEADER_INVALID")
    require(headers.get("X-GitHub-Api-Version")=="2022-11-28","REAL_GIT_TRANSPORT_API_VERSION_INVALID")
    require(headers.get("Authorization")=="Bearer ${GITHUB_TOKEN}","REAL_GIT_TRANSPORT_AUTH_HEADER_INVALID")
    require(policy.get("real_github_requests")==0 and policy.get("real_git_operations")==0 and policy.get("real_branch_created") is False,
            "REAL_GIT_TRANSPORT_PREMATURE_EXECUTION")
    return {
      "artifact":"RATE_REAL_GIT_DATA_TRANSPORT_BINDING_QUALIFICATION_V1",
      "validation_status":"PASS",
      "repository":"pili5420/RATE-Data-Engine",
      "token_source":"GITHUB_TOKEN",
      "workflow_permissions":{"contents":"write"},
      "allowed_requests":EXPECTED_REQUESTS,
      "object_budget":{"blobs":9,"trees":1,"commits":1,"refs":1},
      "redirect_following":False,"automatic_retry":False,"fallback":False,
      "real_github_requests":0,"real_git_operations":0,"real_branch_created":False,
      "next_gate":"REAL_GIT_DATA_HTTP_EXECUTOR_REHEARSAL",
    }

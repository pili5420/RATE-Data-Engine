"""Bind the one-shot Draft-PR authorization to the qualified GitHub transport policy."""
from __future__ import annotations
from typing import Any, Mapping
from .intraday_activation_candidate_review import canonical_digest

class DraftPRTransportExecutionAuthorizationError(RuntimeError): pass
def require(c,r):
    if not c: raise DraftPRTransportExecutionAuthorizationError(r)

def validate_draft_pr_transport_execution_authorization(
    execution_authorization: Mapping[str,Any],
    draft_pr_authorization: Mapping[str,Any],
    transport_binding: Mapping[str,Any],
    *,
    expected_execution_authorization_sha256: str,
    expected_draft_pr_authorization_sha256: str,
    expected_transport_binding_sha256: str,
) -> dict[str,Any]:
    require(canonical_digest(draft_pr_authorization)==expected_draft_pr_authorization_sha256,
            "DRAFT_PR_TRANSPORT_EXEC_DRAFT_AUTH_HASH_MISMATCH")
    require(draft_pr_authorization.get("artifact")=="RATE_REAL_DRAFT_ACTIVATION_PR_CREATION_AUTHORIZATION_QUALIFICATION_V1"
            and draft_pr_authorization.get("validation_status")=="PASS",
            "DRAFT_PR_TRANSPORT_EXEC_DRAFT_AUTH_NOT_PASS")
    require(canonical_digest(transport_binding)==expected_transport_binding_sha256,
            "DRAFT_PR_TRANSPORT_EXEC_BINDING_HASH_MISMATCH")
    require(transport_binding.get("artifact")=="RATE_REAL_DRAFT_ACTIVATION_PR_TRANSPORT_BINDING_QUALIFICATION_V1"
            and transport_binding.get("validation_status")=="PASS",
            "DRAFT_PR_TRANSPORT_EXEC_BINDING_NOT_PASS")
    require(transport_binding.get("repository")=="pili5420/RATE-Data-Engine"
            and transport_binding.get("token_source")=="GITHUB_TOKEN"
            and transport_binding.get("workflow_permissions")=={"contents":"read","pull-requests":"write"},
            "DRAFT_PR_TRANSPORT_EXEC_TRANSPORT_SCOPE_INVALID")
    require(transport_binding.get("automatic_retry") is False
            and transport_binding.get("fallback") is False,
            "DRAFT_PR_TRANSPORT_EXEC_TRANSPORT_RETRY_INVALID")

    require(canonical_digest(execution_authorization)==expected_execution_authorization_sha256,
            "DRAFT_PR_TRANSPORT_EXEC_AUTH_HASH_MISMATCH")
    require(execution_authorization.get("artifact")=="RATE_REAL_DRAFT_PR_TRANSPORT_EXECUTION_AUTHORIZATION_V1"
            and execution_authorization.get("status")=="REAL_DRAFT_PR_TRANSPORT_EXECUTION_AUTHORIZED",
            "DRAFT_PR_TRANSPORT_EXEC_AUTH_STATUS_INVALID")
    require(execution_authorization.get("draft_pr_authorization_sha256")==expected_draft_pr_authorization_sha256
            and execution_authorization.get("transport_binding_sha256")==expected_transport_binding_sha256,
            "DRAFT_PR_TRANSPORT_EXEC_AUTH_BINDING_MISMATCH")
    require(execution_authorization.get("head")==draft_pr_authorization.get("head")
            and execution_authorization.get("base")=="main"
            and execution_authorization.get("receipt_sha256")==draft_pr_authorization.get("receipt_sha256"),
            "DRAFT_PR_TRANSPORT_EXEC_TARGET_BINDING_INVALID")
    require(execution_authorization.get("single_use") is True
            and execution_authorization.get("execution_consumed") is False
            and execution_authorization.get("create_attempts")==1
            and execution_authorization.get("automatic_retry_allowed") is False
            and execution_authorization.get("fallback_allowed") is False,
            "DRAFT_PR_TRANSPORT_EXEC_SINGLE_USE_INVALID")
    require(execution_authorization.get("ready_for_review_allowed") is False
            and execution_authorization.get("merge_allowed") is False
            and execution_authorization.get("real_github_requests")==0
            and execution_authorization.get("real_pull_request_created") is False,
            "DRAFT_PR_TRANSPORT_EXEC_PREMATURE_STATE")
    return {
      "artifact":"RATE_REAL_DRAFT_PR_TRANSPORT_EXECUTION_AUTHORIZATION_QUALIFICATION_V1",
      "validation_status":"PASS",
      "execution_authorization_sha256":expected_execution_authorization_sha256,
      "draft_pr_authorization_sha256":expected_draft_pr_authorization_sha256,
      "transport_binding_sha256":expected_transport_binding_sha256,
      "head":draft_pr_authorization["head"],"base":"main",
      "receipt_sha256":draft_pr_authorization["receipt_sha256"],
      "single_use":True,"execution_consumed":False,"create_attempts":1,
      "automatic_retry_allowed":False,"fallback_allowed":False,
      "real_github_requests":0,"real_pull_request_created":False,
      "next_gate":"REAL_DRAFT_PR_HTTP_EXECUTOR_REHEARSAL"
    }

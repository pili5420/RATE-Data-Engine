"""Pure authorization gate for one real Draft activation pull request creation."""
from __future__ import annotations
from typing import Any, Mapping
from .intraday_activation_candidate_review import canonical_digest

class RealDraftPRAuthorizationError(RuntimeError): pass
def require(c,r):
    if not c: raise RealDraftPRAuthorizationError(r)

def validate_real_draft_pr_creation_authorization(
    authorization: Mapping[str,Any],
    independent_review: Mapping[str,Any],
    *,
    expected_authorization_sha256: str,
    expected_review_sha256: str,
    expected_head_branch: str,
    expected_receipt_sha256: str,
) -> dict[str,Any]:
    require(isinstance(independent_review,Mapping),"REAL_DRAFT_PR_REVIEW_INVALID")
    require(canonical_digest(independent_review)==expected_review_sha256,"REAL_DRAFT_PR_REVIEW_HASH_MISMATCH")
    require(independent_review.get("artifact")=="RATE_INDEPENDENT_ACTIVATION_DRAFT_PR_REVIEW_V1"
            and independent_review.get("validation_status")=="PASS"
            and independent_review.get("review_disposition")=="READY_FOR_CONTROL_CENTER_REAL_DRAFT_PR_AUTHORIZATION",
            "REAL_DRAFT_PR_REVIEW_NOT_PASS")
    require(independent_review.get("head")==expected_head_branch
            and independent_review.get("base")=="main"
            and independent_review.get("draft") is True,
            "REAL_DRAFT_PR_REVIEW_BINDING_INVALID")
    require(independent_review.get("real_pull_request_created") is False
            and independent_review.get("merge_allowed") is False,
            "REAL_DRAFT_PR_REVIEW_PREMATURE_STATE")

    require(isinstance(authorization,Mapping),"REAL_DRAFT_PR_AUTH_INVALID")
    require(canonical_digest(authorization)==expected_authorization_sha256,"REAL_DRAFT_PR_AUTH_HASH_MISMATCH")
    require(authorization.get("artifact")=="RATE_REAL_DRAFT_ACTIVATION_PR_CREATION_AUTHORIZATION_V1"
            and authorization.get("status")=="REAL_DRAFT_PR_CREATION_AUTHORIZED",
            "REAL_DRAFT_PR_AUTH_STATUS_INVALID")
    require(authorization.get("independent_review_sha256")==expected_review_sha256,
            "REAL_DRAFT_PR_AUTH_REVIEW_BINDING_MISMATCH")
    require(authorization.get("receipt_sha256")==expected_receipt_sha256,
            "REAL_DRAFT_PR_AUTH_RECEIPT_BINDING_MISMATCH")
    require(authorization.get("head")==expected_head_branch
            and authorization.get("base")=="main"
            and authorization.get("draft") is True,
            "REAL_DRAFT_PR_AUTH_BRANCH_BINDING_INVALID")
    require(authorization.get("single_use") is True
            and authorization.get("pr_creation_consumed") is False
            and authorization.get("automatic_retry_allowed") is False
            and authorization.get("fallback_allowed") is False,
            "REAL_DRAFT_PR_AUTH_SINGLE_USE_BOUNDARY_INVALID")
    require(authorization.get("create_draft_pr_count")==1
            and authorization.get("ready_for_review_allowed") is False
            and authorization.get("auto_merge_allowed") is False
            and authorization.get("merge_queue_allowed") is False
            and authorization.get("merge_allowed") is False,
            "REAL_DRAFT_PR_AUTH_OPERATION_BOUNDARY_INVALID")
    require(authorization.get("real_github_requests")==0
            and authorization.get("real_pull_request_created") is False
            and authorization.get("production_credit")==0
            and authorization.get("cer081_credit")==0,
            "REAL_DRAFT_PR_AUTH_PREMATURE_EXECUTION")

    return {
      "artifact":"RATE_REAL_DRAFT_ACTIVATION_PR_CREATION_AUTHORIZATION_QUALIFICATION_V1",
      "validation_status":"PASS",
      "authorization_sha256":expected_authorization_sha256,
      "independent_review_sha256":expected_review_sha256,
      "receipt_sha256":expected_receipt_sha256,
      "head":expected_head_branch,"base":"main","draft":True,
      "single_use":True,"pr_creation_consumed":False,
      "automatic_retry_allowed":False,"fallback_allowed":False,
      "create_draft_pr_count":1,
      "ready_for_review_allowed":False,"auto_merge_allowed":False,
      "merge_queue_allowed":False,"merge_allowed":False,
      "real_github_requests":0,"real_pull_request_created":False,
      "production_credit":0,"cer081_credit":0,
      "next_gate":"SEPARATE_REAL_DRAFT_PR_EXECUTOR",
    }

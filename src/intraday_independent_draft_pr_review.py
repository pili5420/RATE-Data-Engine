"""Independent offline review gate for the synthetic Draft activation PR rehearsal."""
from __future__ import annotations
from typing import Any, Mapping
from .intraday_activation_candidate_review import canonical_digest

class DraftPRIndependentReviewError(RuntimeError): pass
def require(c,r):
    if not c: raise DraftPRIndependentReviewError(r)

def validate_draft_pr_rehearsal_review(
    rehearsal: Mapping[str,Any],
    *,
    expected_rehearsal_sha256: str,
    expected_head_branch: str,
    expected_base_branch: str="main",
) -> dict[str,Any]:
    require(isinstance(rehearsal,Mapping),"DRAFT_PR_REVIEW_INPUT_INVALID")
    require(canonical_digest(rehearsal)==expected_rehearsal_sha256,"DRAFT_PR_REVIEW_HASH_MISMATCH")
    require(rehearsal.get("artifact")=="RATE_DRAFT_ACTIVATION_PR_EXECUTOR_REHEARSAL_V1"
            and rehearsal.get("validation_status")=="PASS","DRAFT_PR_REVIEW_NOT_PASS")
    require(rehearsal.get("receipt_sha256") and len(rehearsal["receipt_sha256"])==64,
            "DRAFT_PR_REVIEW_RECEIPT_INVALID")
    require(rehearsal.get("head")==expected_head_branch
            and expected_head_branch.startswith("activation/rate-v11-intraday-")
            and rehearsal.get("base")==expected_base_branch=="main",
            "DRAFT_PR_REVIEW_BRANCH_BINDING_INVALID")
    require(rehearsal.get("draft") is True
            and rehearsal.get("draft_pr_create_attempts")==1,
            "DRAFT_PR_REVIEW_CREATE_BOUNDARY_INVALID")
    require(rehearsal.get("ready_for_review") is False
            and rehearsal.get("auto_merge_allowed") is False
            and rehearsal.get("merge_queue_allowed") is False
            and rehearsal.get("merge_allowed") is False,
            "DRAFT_PR_REVIEW_MERGE_BOUNDARY_INVALID")
    require(rehearsal.get("real_pull_request_created") is False
            and rehearsal.get("production_credit")==0
            and rehearsal.get("cer081_credit")==0,
            "DRAFT_PR_REVIEW_PREMATURE_REAL_STATE")
    return {
      "artifact":"RATE_INDEPENDENT_ACTIVATION_DRAFT_PR_REVIEW_V1",
      "validation_status":"PASS",
      "review_disposition":"READY_FOR_CONTROL_CENTER_REAL_DRAFT_PR_AUTHORIZATION",
      "rehearsal_sha256":expected_rehearsal_sha256,
      "head":expected_head_branch,"base":"main","draft":True,
      "draft_pr_create_attempts":1,
      "real_pull_request_created":False,
      "merge_allowed":False,
      "production_credit":0,"cer081_credit":0,
    }

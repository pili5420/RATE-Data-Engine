"""Independent review of one completed real Git activation transaction evidence package."""
from __future__ import annotations
from typing import Any, Mapping
from .intraday_activation_candidate_review import canonical_digest

class RealGitExecutionEvidenceReviewError(RuntimeError): pass
def require(c,r):
    if not c: raise RealGitExecutionEvidenceReviewError(r)

def validate_real_git_execution_evidence(
    evidence: Mapping[str,Any],
    *,
    expected_evidence_sha256: str,
    expected_pre_execution_main_sha: str,
    expected_target_branch: str,
    expected_transaction_plan_sha256: str,
    expected_candidate_manifest_sha256: str,
    expected_receipt_sha256: str,
) -> dict[str,Any]:
    require(canonical_digest(evidence)==expected_evidence_sha256,"REAL_GIT_EVIDENCE_HASH_MISMATCH")
    require(evidence.get("artifact")=="RATE_REAL_GIT_TRANSACTION_EXECUTION_EVIDENCE_V1"
            and evidence.get("execution_status")=="PASS","REAL_GIT_EVIDENCE_NOT_PASS")
    require(evidence.get("pre_execution_main_sha")==expected_pre_execution_main_sha,
            "REAL_GIT_EVIDENCE_MAIN_BINDING_MISMATCH")
    require(evidence.get("post_execution_main_sha")==expected_pre_execution_main_sha
            and evidence.get("main_ref_unchanged") is True,
            "REAL_GIT_EVIDENCE_MAIN_MUTATED")
    require(evidence.get("target_branch")==expected_target_branch
            and expected_target_branch.startswith("activation/rate-v11-intraday-"),
            "REAL_GIT_EVIDENCE_BRANCH_BINDING_MISMATCH")
    require(evidence.get("transaction_plan_sha256")==expected_transaction_plan_sha256
            and evidence.get("candidate_manifest_sha256")==expected_candidate_manifest_sha256,
            "REAL_GIT_EVIDENCE_PLAN_BINDING_MISMATCH")
    require(evidence.get("receipt_sha256")==expected_receipt_sha256
            and evidence.get("receipt_state")=="CONSUMED_BEFORE_GIT_MUTATION"
            and evidence.get("receipt_persisted_before_first_git_mutation") is True,
            "REAL_GIT_EVIDENCE_RECEIPT_BINDING_INVALID")
    require(evidence.get("blob_count")==9
            and evidence.get("tree_count")==1
            and evidence.get("commit_count")==1
            and evidence.get("branch_ref_create_count")==1,
            "REAL_GIT_EVIDENCE_OBJECT_BUDGET_INVALID")
    require(evidence.get("branch_ref_readback_verified") is True
            and evidence.get("branch_ref_target_sha")==evidence.get("commit_sha"),
            "REAL_GIT_EVIDENCE_BRANCH_READBACK_INVALID")
    require(evidence.get("commit_parent_sha")==expected_pre_execution_main_sha,
            "REAL_GIT_EVIDENCE_COMMIT_PARENT_INVALID")
    require(evidence.get("automatic_retry_count")==0
            and evidence.get("fallback_used") is False
            and evidence.get("merge_performed") is False,
            "REAL_GIT_EVIDENCE_RETRY_OR_MERGE_INVALID")
    require(evidence.get("draft_pull_request_created") is True
            and evidence.get("draft_pull_request_draft") is True
            and evidence.get("draft_pull_request_base")=="main"
            and evidence.get("draft_pull_request_head")==expected_target_branch,
            "REAL_GIT_EVIDENCE_DRAFT_PR_INVALID")
    require(evidence.get("production_credit")==0 and evidence.get("cer081_credit")==0,
            "REAL_GIT_EVIDENCE_PREMATURE_CREDIT")
    return {
      "artifact":"RATE_REAL_GIT_TRANSACTION_EXECUTION_REVIEW_V1",
      "validation_status":"PASS",
      "review_disposition":"READY_FOR_ACTIVATION_DRAFT_PR_INDEPENDENT_REVIEW",
      "evidence_sha256":expected_evidence_sha256,
      "pre_execution_main_sha":expected_pre_execution_main_sha,
      "activation_commit_sha":evidence["commit_sha"],
      "target_branch":expected_target_branch,
      "receipt_sha256":expected_receipt_sha256,
      "main_ref_unchanged":True,
      "merge_performed":False,
      "production_credit":0,"cer081_credit":0
    }

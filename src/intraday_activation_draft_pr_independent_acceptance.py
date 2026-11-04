"""Independent acceptance gate for one real Draft activation PR.

This gate reviews the real Draft PR metadata and CI evidence after the real Git
transaction has already passed the execution evidence review. It performs no merge.
"""
from __future__ import annotations
from typing import Any, Mapping
from .intraday_activation_candidate_review import canonical_digest
from .intraday_activation_apply_authorization import EXPECTED_PATHS

class ActivationDraftPRAcceptanceError(RuntimeError): pass
def require(condition: bool, reason: str) -> None:
    if not condition:
        raise ActivationDraftPRAcceptanceError(reason)

def validate_activation_draft_pr_acceptance(
    execution_review: Mapping[str,Any],
    draft_pr_evidence: Mapping[str,Any],
    *,
    expected_execution_review_sha256: str,
    expected_draft_pr_evidence_sha256: str,
    expected_target_branch: str,
    expected_activation_commit_sha: str,
) -> dict[str,Any]:
    require(canonical_digest(execution_review)==expected_execution_review_sha256,
            "ACTIVATION_PR_EXECUTION_REVIEW_HASH_MISMATCH")
    require(execution_review.get("artifact")=="RATE_REAL_GIT_TRANSACTION_EXECUTION_REVIEW_V1"
            and execution_review.get("validation_status")=="PASS"
            and execution_review.get("review_disposition")=="READY_FOR_ACTIVATION_DRAFT_PR_INDEPENDENT_REVIEW",
            "ACTIVATION_PR_EXECUTION_REVIEW_NOT_PASS")
    require(execution_review.get("target_branch")==expected_target_branch
            and execution_review.get("activation_commit_sha")==expected_activation_commit_sha,
            "ACTIVATION_PR_EXECUTION_BINDING_MISMATCH")

    require(canonical_digest(draft_pr_evidence)==expected_draft_pr_evidence_sha256,
            "ACTIVATION_PR_EVIDENCE_HASH_MISMATCH")
    require(draft_pr_evidence.get("artifact")=="RATE_REAL_ACTIVATION_DRAFT_PR_EVIDENCE_V1"
            and draft_pr_evidence.get("status")=="OPEN",
            "ACTIVATION_PR_EVIDENCE_STATUS_INVALID")
    require(isinstance(draft_pr_evidence.get("pull_request_number"),int)
            and draft_pr_evidence["pull_request_number"]>0,
            "ACTIVATION_PR_NUMBER_INVALID")
    require(draft_pr_evidence.get("head_branch")==expected_target_branch
            and draft_pr_evidence.get("base_branch")=="main"
            and draft_pr_evidence.get("head_sha")==expected_activation_commit_sha,
            "ACTIVATION_PR_BRANCH_BINDING_INVALID")
    require(draft_pr_evidence.get("draft") is True
            and draft_pr_evidence.get("ready_for_review") is False
            and draft_pr_evidence.get("merged") is False
            and draft_pr_evidence.get("auto_merge_enabled") is False
            and draft_pr_evidence.get("merge_queue_enabled") is False,
            "ACTIVATION_PR_DRAFT_BOUNDARY_INVALID")

    files=draft_pr_evidence.get("changed_files")
    require(isinstance(files,list) and len(files)==len(EXPECTED_PATHS)
            and set(files)==set(EXPECTED_PATHS),
            "ACTIVATION_PR_FILE_SET_INVALID")
    require(draft_pr_evidence.get("changed_file_count")==len(EXPECTED_PATHS),
            "ACTIVATION_PR_FILE_COUNT_INVALID")
    require(draft_pr_evidence.get("unexpected_files")==[],
            "ACTIVATION_PR_UNEXPECTED_FILE_PRESENT")

    ci=draft_pr_evidence.get("ci")
    require(isinstance(ci,Mapping)
            and ci.get("exact_head_sha")==expected_activation_commit_sha
            and ci.get("required_checks_total")>=1
            and ci.get("required_checks_success")==ci.get("required_checks_total")
            and ci.get("required_checks_failure")==0
            and ci.get("required_checks_pending")==0,
            "ACTIVATION_PR_CI_NOT_GREEN")
    require(draft_pr_evidence.get("main_sha_at_review")
            ==execution_review.get("pre_execution_main_sha"),
            "ACTIVATION_PR_MAIN_BASE_DRIFT")
    require(draft_pr_evidence.get("merge_performed") is False
            and draft_pr_evidence.get("production_credit")==0
            and draft_pr_evidence.get("cer081_credit")==0,
            "ACTIVATION_PR_PREMATURE_MERGE_OR_CREDIT")

    return {
      "artifact":"RATE_ACTIVATION_DRAFT_PR_INDEPENDENT_ACCEPTANCE_V1",
      "validation_status":"PASS",
      "review_disposition":"READY_FOR_CONTROL_CENTER_ACTIVATION_MERGE_AUTHORIZATION",
      "execution_review_sha256":expected_execution_review_sha256,
      "draft_pr_evidence_sha256":expected_draft_pr_evidence_sha256,
      "pull_request_number":draft_pr_evidence["pull_request_number"],
      "head_branch":expected_target_branch,
      "head_sha":expected_activation_commit_sha,
      "base_branch":"main",
      "draft":True,
      "changed_file_count":len(EXPECTED_PATHS),
      "merge_performed":False,
      "production_credit":0,
      "cer081_credit":0,
      "next_gate":"CONTROL_CENTER_ACTIVATION_MERGE_AUTHORIZATION",
    }

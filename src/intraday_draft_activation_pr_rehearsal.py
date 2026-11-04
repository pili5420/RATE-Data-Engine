"""Synthetic rehearsal for creating the one authorized Draft activation PR after durable Git orchestration."""
from __future__ import annotations
from copy import deepcopy
from typing import Any, Mapping
from .intraday_activation_candidate_review import canonical_digest

class DraftPRRehearsalError(RuntimeError): pass
def require(c,r):
    if not c: raise DraftPRRehearsalError(r)

class SyntheticDraftPRBackend:
    def __init__(self, *, fail_create=False):
        self.fail_create=fail_create
        self.calls=[]
        self.prs=[]
        self.attempted_receipts=set()
    def create_draft_pr(self, *, receipt_sha256, title, head, base, body):
        require(receipt_sha256 not in self.attempted_receipts,"DRAFT_PR_RECEIPT_ALREADY_ATTEMPTED")
        self.attempted_receipts.add(receipt_sha256)
        self.calls.append({"op":"CREATE_DRAFT_PR","head":head,"base":base,"draft":True})
        if self.fail_create:
            raise RuntimeError("SYNTHETIC_DRAFT_PR_CREATE_FAILED")
        pr={"number":1,"title":title,"head":head,"base":base,"draft":True,"body":body}
        self.prs.append(deepcopy(pr))
        return pr

def rehearse_draft_activation_pr(orchestration: Mapping[str,Any], backend:SyntheticDraftPRBackend, *, expected_orchestration_sha256:str):
    require(canonical_digest(orchestration)==expected_orchestration_sha256,"DRAFT_PR_ORCHESTRATION_HASH_MISMATCH")
    require(orchestration.get("artifact")=="RATE_DURABLE_RECEIPT_THEN_GIT_ORCHESTRATION_REHEARSAL_V1"
            and orchestration.get("validation_status")=="PASS","DRAFT_PR_ORCHESTRATION_NOT_PASS")
    require(orchestration.get("receipt_persisted_before_git") is True
            and orchestration.get("receipt_state")=="CONSUMED_BEFORE_GIT_MUTATION"
            and orchestration.get("git_mutations_before_receipt")==0,"DRAFT_PR_RECEIPT_BOUNDARY_INVALID")
    require(orchestration.get("synthetic_branch_created") is True
            and orchestration.get("synthetic_branch_ref_created_last") is True
            and isinstance(orchestration.get("synthetic_commit_sha"),str),"DRAFT_PR_GIT_RESULT_INVALID")
    require(orchestration.get("real_git_operations")==0
            and orchestration.get("real_repository_writes")==0
            and orchestration.get("real_pull_request_created") is False
            and orchestration.get("merge_performed") is False,"DRAFT_PR_PREMATURE_REAL_STATE")
    require(type(backend) is SyntheticDraftPRBackend,"DRAFT_PR_REAL_BACKEND_FORBIDDEN")
    head=orchestration["target_branch"]; base="main"
    require(head.startswith("activation/rate-v11-intraday-") and head!="main","DRAFT_PR_HEAD_INVALID")
    title="RATE V11 Intraday Activation Candidate"
    body=("Synthetic rehearsal only. Durable receipt already consumed before Git mutation. "
          "Independent review required before any merge.")
    try:
        pr=backend.create_draft_pr(receipt_sha256=orchestration["receipt_sha256"],title=title,head=head,base=base,body=body)
    except Exception:
        return {
            "artifact":"RATE_DRAFT_ACTIVATION_PR_EXECUTOR_REHEARSAL_V1",
            "validation_status":"BLOCKED",
            "disposition":"NON_RETRYABLE_AFTER_DURABLE_CONSUMPTION",
            "receipt_sha256":orchestration["receipt_sha256"],
            "draft_pr_create_attempts":1,
            "real_pull_request_created":False,
            "merge_allowed":False,
            "production_credit":0,"cer081_credit":0,
        }
    require(pr["draft"] is True and pr["head"]==head and pr["base"]=="main","DRAFT_PR_RESULT_BINDING_INVALID")
    return {
        "artifact":"RATE_DRAFT_ACTIVATION_PR_EXECUTOR_REHEARSAL_V1",
        "validation_status":"PASS",
        "receipt_sha256":orchestration["receipt_sha256"],
        "head":head,"base":"main","draft":True,
        "draft_pr_create_attempts":1,
        "ready_for_review":False,"auto_merge_allowed":False,"merge_queue_allowed":False,"merge_allowed":False,
        "real_pull_request_created":False,
        "production_credit":0,"cer081_credit":0,
        "next_gate":"INDEPENDENT_ACTIVATION_DRAFT_PR_REVIEW",
    }

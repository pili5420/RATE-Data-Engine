"""Executor state machine for one authorized real Draft activation PR.

CI accepts only SyntheticDraftPRTransport. No real GitHub request is performed.
"""
from __future__ import annotations
from copy import deepcopy
from typing import Any, Mapping
from .intraday_activation_candidate_review import canonical_digest

class RealDraftPRExecutorError(RuntimeError): pass
def require(c,r):
    if not c: raise RealDraftPRExecutorError(r)

class SyntheticDraftPRTransport:
    def __init__(self, *, fail_create=False):
        self.fail_create=fail_create
        self.calls=[]
        self.prs=[]
        self.attempted_receipts=set()
    def find(self, *, head, base):
        self.calls.append({"op":"FIND","head":head,"base":base})
        for pr in self.prs:
            if pr["head"]==head and pr["base"]==base:
                return deepcopy(pr)
        return None
    def create(self, *, receipt_sha256, title, head, base, body, draft):
        require(receipt_sha256 not in self.attempted_receipts,"REAL_DRAFT_PR_RECEIPT_ALREADY_ATTEMPTED")
        self.attempted_receipts.add(receipt_sha256)
        self.calls.append({"op":"CREATE","head":head,"base":base,"draft":draft})
        if self.fail_create:
            raise RuntimeError("SYNTHETIC_REAL_DRAFT_PR_CREATE_FAILED")
        pr={"number":1,"title":title,"head":head,"base":base,"body":body,"draft":draft}
        self.prs.append(deepcopy(pr))
        return pr

def execute_real_draft_pr(
    authorization_qualification: Mapping[str,Any],
    transport: SyntheticDraftPRTransport,
    *,
    expected_authorization_qualification_sha256: str,
) -> dict[str,Any]:
    require(
        canonical_digest(authorization_qualification)
        == expected_authorization_qualification_sha256,
        "REAL_DRAFT_PR_EXEC_AUTH_QUAL_HASH_MISMATCH",
    )
    require(
        authorization_qualification.get("artifact")
        == "RATE_REAL_DRAFT_ACTIVATION_PR_CREATION_AUTHORIZATION_QUALIFICATION_V1"
        and authorization_qualification.get("validation_status")=="PASS",
        "REAL_DRAFT_PR_EXEC_AUTH_QUAL_NOT_PASS",
    )
    require(
        authorization_qualification.get("single_use") is True
        and authorization_qualification.get("pr_creation_consumed") is False
        and authorization_qualification.get("automatic_retry_allowed") is False
        and authorization_qualification.get("fallback_allowed") is False,
        "REAL_DRAFT_PR_EXEC_SINGLE_USE_BOUNDARY_INVALID",
    )
    require(
        authorization_qualification.get("create_draft_pr_count")==1
        and authorization_qualification.get("ready_for_review_allowed") is False
        and authorization_qualification.get("auto_merge_allowed") is False
        and authorization_qualification.get("merge_queue_allowed") is False
        and authorization_qualification.get("merge_allowed") is False,
        "REAL_DRAFT_PR_EXEC_OPERATION_BOUNDARY_INVALID",
    )
    require(
        authorization_qualification.get("real_github_requests")==0
        and authorization_qualification.get("real_pull_request_created") is False,
        "REAL_DRAFT_PR_EXEC_PREMATURE_STATE",
    )
    require(type(transport) is SyntheticDraftPRTransport,"REAL_DRAFT_PR_EXEC_REAL_TRANSPORT_FORBIDDEN_IN_CI")

    head=authorization_qualification["head"]
    base=authorization_qualification["base"]
    receipt=authorization_qualification["receipt_sha256"]
    require(
        isinstance(head,str) and head.startswith("activation/rate-v11-intraday-")
        and base=="main",
        "REAL_DRAFT_PR_EXEC_BRANCH_INVALID",
    )

    existing=transport.find(head=head,base=base)
    if existing is not None:
        if existing.get("draft") is True:
            raise RealDraftPRExecutorError("REAL_DRAFT_PR_EXEC_ALREADY_CONSUMED")
        raise RealDraftPRExecutorError("REAL_DRAFT_PR_EXEC_EXISTING_PR_CONFLICT")

    require(receipt not in transport.attempted_receipts,"REAL_DRAFT_PR_RECEIPT_ALREADY_ATTEMPTED")
    title="RATE V11 Intraday Activation Candidate"
    body=(
        "Activation candidate only. Durable receipt consumed before Git mutation. "
        "Independent review required. Do not mark ready or merge without separate authorization."
    )
    try:
        pr=transport.create(
            receipt_sha256=receipt,title=title,head=head,base=base,body=body,draft=True
        )
    except Exception:
        return {
          "artifact":"RATE_REAL_DRAFT_ACTIVATION_PR_EXECUTION_RESULT_V1",
          "validation_status":"BLOCKED",
          "disposition":"NON_RETRYABLE_AFTER_DURABLE_CONSUMPTION",
          "receipt_sha256":receipt,
          "create_attempts":1,
          "pr_creation_consumed":True,
          "real_transport_used":False,
          "real_github_requests":0,
          "real_pull_request_created":False,
          "merge_allowed":False,
          "production_credit":0,"cer081_credit":0,
        }

    require(pr["draft"] is True and pr["head"]==head and pr["base"]=="main",
            "REAL_DRAFT_PR_EXEC_RESULT_BINDING_INVALID")
    return {
      "artifact":"RATE_REAL_DRAFT_ACTIVATION_PR_EXECUTION_RESULT_V1",
      "validation_status":"PASS",
      "authorization_qualification_sha256":expected_authorization_qualification_sha256,
      "receipt_sha256":receipt,
      "head":head,"base":"main","draft":True,
      "create_attempts":1,
      "pr_creation_consumed":True,
      "ready_for_review":False,"auto_merge_allowed":False,"merge_queue_allowed":False,"merge_allowed":False,
      "real_transport_used":False,
      "real_github_requests":0,"real_pull_request_created":False,
      "production_credit":0,"cer081_credit":0,
      "next_gate":"REAL_GITHUB_DRAFT_PR_TRANSPORT_BINDING_AND_EXECUTION",
    }

"""Pure Control Center acceptance gate for the qualified Cloudflare authority store.

This gate is role-specific: it may accept Cloudflare Workers+D1 only as the durable
receipt store for future real-Git execution. It cannot accept an intraday market-data
provider, resolve the intraday dependency or authorize the real Git transaction.
"""
from __future__ import annotations

import re
from typing import Any, Mapping

from .intraday_activation_candidate_review import canonical_digest

HEX40=re.compile(r"^[0-9a-f]{40}$")
HEX64=re.compile(r"^[0-9a-f]{64}$")
DECISION_ID=re.compile(r"^[A-Za-z0-9._-]{1,128}$")
ROLE="REAL_GIT_EXECUTION_CONSUMPTION_RECEIPT_STORE"
PROVIDER="CLOUDFLARE_WORKERS_D1"
PLAN="WORKERS_FREE"


class CloudflareAuthorityStoreAcceptanceError(RuntimeError):
    pass


def require(condition: bool, reason: str) -> None:
    if not condition:
        raise CloudflareAuthorityStoreAcceptanceError(reason)


def _sha40(value: Any, reason: str) -> str:
    text=str(value or "").lower()
    require(bool(HEX40.fullmatch(text)),reason)
    return text


def _sha64(value: Any, reason: str) -> str:
    text=str(value or "").lower()
    require(bool(HEX64.fullmatch(text)),reason)
    return text


def validate_cloudflare_authority_store_acceptance(
    decision: Mapping[str,Any],
    evidence_review: Mapping[str,Any],
    *,
    expected_decision_sha256: str,
    expected_evidence_review_sha256: str,
    expected_current_main_sha: str,
    expected_control_center_decision_id: str,
) -> dict[str,Any]:
    decision_hash=_sha64(expected_decision_sha256,"CF_STORE_ACCEPT_EXPECTED_DECISION_HASH_INVALID")
    evidence_hash=_sha64(expected_evidence_review_sha256,"CF_STORE_ACCEPT_EXPECTED_EVIDENCE_HASH_INVALID")
    main=_sha40(expected_current_main_sha,"CF_STORE_ACCEPT_EXPECTED_MAIN_INVALID")
    require(
        isinstance(expected_control_center_decision_id,str)
        and bool(DECISION_ID.fullmatch(expected_control_center_decision_id)),
        "CF_STORE_ACCEPT_EXPECTED_DECISION_ID_INVALID",
    )

    require(isinstance(evidence_review,Mapping),"CF_STORE_ACCEPT_EVIDENCE_INVALID")
    require(canonical_digest(evidence_review)==evidence_hash,"CF_STORE_ACCEPT_EVIDENCE_HASH_MISMATCH")
    require(
        evidence_review.get("artifact")
        =="RATE_CLOUDFLARE_D1_REAL_QUALIFICATION_EVIDENCE_REVIEW_V1"
        and evidence_review.get("validation_status")=="PASS"
        and evidence_review.get("review_disposition")
        =="READY_FOR_CONTROL_CENTER_CLOUDFLARE_PROVIDER_ACCEPTANCE",
        "CF_STORE_ACCEPT_EVIDENCE_NOT_PASS",
    )
    require(
        evidence_review.get("current_main_sha")==main
        and evidence_review.get("request_count")==17
        and evidence_review.get("cleanup_closed") is True
        and evidence_review.get("residual_resource_count")==0,
        "CF_STORE_ACCEPT_EVIDENCE_BOUNDARY_INVALID",
    )
    require(
        evidence_review.get("provider_accepted") is False
        and evidence_review.get("provider_qualified") is False
        and evidence_review.get("production_eligible") is False
        and evidence_review.get("external_dependency_resolved") is False
        and evidence_review.get("production_credit")==0
        and evidence_review.get("cer081_credit")==0,
        "CF_STORE_ACCEPT_EVIDENCE_PREMATURE_STATE",
    )

    require(isinstance(decision,Mapping),"CF_STORE_ACCEPT_DECISION_INVALID")
    require(canonical_digest(decision)==decision_hash,"CF_STORE_ACCEPT_DECISION_HASH_MISMATCH")
    require(
        decision.get("artifact")=="RATE_CLOUDFLARE_AUTHORITY_STORE_PROVIDER_ACCEPTANCE_DECISION_V1"
        and decision.get("status")=="AUTHORITY_STORE_PROVIDER_ACCEPTANCE_AUTHORIZED",
        "CF_STORE_ACCEPT_DECISION_STATUS_INVALID",
    )
    require(
        decision.get("control_center_decision_id")==expected_control_center_decision_id,
        "CF_STORE_ACCEPT_DECISION_ID_MISMATCH",
    )
    require(
        decision.get("evidence_review_sha256")==evidence_hash
        and decision.get("current_main_sha")==main,
        "CF_STORE_ACCEPT_DECISION_EVIDENCE_BINDING_MISMATCH",
    )
    require(
        decision.get("provider")==PROVIDER
        and decision.get("plan")==PLAN
        and decision.get("accepted_role")==ROLE,
        "CF_STORE_ACCEPT_ROLE_BINDING_INVALID",
    )
    require(
        decision.get("authority_store_provider_acceptance") is True
        and decision.get("intraday_market_data_provider_acceptance") is False,
        "CF_STORE_ACCEPT_PROVIDER_ROLE_SCOPE_INVALID",
    )
    require(
        decision.get("real_git_transaction_execution_allowed") is False
        and decision.get("production_activation_allowed") is False
        and decision.get("external_intraday_dependency_resolved") is False
        and decision.get("production_credit")==0
        and decision.get("cer081_credit")==0,
        "CF_STORE_ACCEPT_FORBIDDEN_DOWNSTREAM_STATE",
    )

    return {
        "artifact":"RATE_CLOUDFLARE_AUTHORITY_STORE_PROVIDER_ACCEPTANCE_V1",
        "validation_status":"PASS",
        "control_center_decision_id":expected_control_center_decision_id,
        "decision_sha256":decision_hash,
        "evidence_review_sha256":evidence_hash,
        "current_main_sha":main,
        "provider":PROVIDER,
        "plan":PLAN,
        "accepted_role":ROLE,
        "authority_store_provider_accepted":True,
        "authority_store_provider_qualified":True,
        "intraday_market_data_provider_accepted":False,
        "real_git_transaction_execution_allowed":False,
        "production_activation_allowed":False,
        "external_intraday_dependency_resolved":False,
        "production_credit":0,
        "cer081_credit":0,
        "next_gate":"REAL_GIT_EXECUTION_WITH_ACCEPTED_AUTHORITY_STORE_READINESS",
    }

"""Synthetic durable consumption fence for one authorized Fugle live qualification.

CI uses only an in-memory backend. The contract proves that single-use state is
persisted and read back before credential access or any provider request.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import re
from typing import Any, Mapping

HEX40 = re.compile(r"^[0-9a-f]{40}$")
HEX64 = re.compile(r"^[0-9a-f]{64}$")


class FugleConsumptionFenceError(RuntimeError):
    pass


class AmbiguousFenceWrite(RuntimeError):
    pass


def require(condition: bool, reason: str) -> None:
    if not condition:
        raise FugleConsumptionFenceError(reason)


def canonical_digest(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _hex40(value: Any, reason: str) -> str:
    text=str(value or "").lower()
    require(bool(HEX40.fullmatch(text)), reason)
    return text


def _hex64(value: Any, reason: str) -> str:
    text=str(value or "").lower()
    require(bool(HEX64.fullmatch(text)), reason)
    return text


def fence_key(authorization_sha256: str) -> str:
    value=_hex64(authorization_sha256, "FUGLE_FENCE_AUTH_HASH_INVALID")
    return "rate/fugle/single-live/consumed/" + value[:32]


@dataclass
class SyntheticWriteOnceFenceStore:
    fail_mode: str | None = None

    def __post_init__(self) -> None:
        self.values: dict[str, dict[str, Any]] = {}
        self.write_attempts=0
        self.read_attempts=0
        self.update_attempts=0
        self.delete_attempts=0

    def read(self, key: str) -> dict[str, Any] | None:
        self.read_attempts += 1
        value=self.values.get(key)
        return None if value is None else dict(value)

    def create_once(self, key: str, value: Mapping[str, Any]) -> None:
        self.write_attempts += 1
        if self.fail_mode=="BEFORE_CREATE":
            raise RuntimeError("SYNTHETIC_FUGLE_FENCE_FAIL_BEFORE_CREATE")
        require(key not in self.values, "FUGLE_FENCE_ALREADY_CONSUMED")
        self.values[key]=dict(value)
        if self.fail_mode=="AMBIGUOUS_AFTER_CREATE":
            raise AmbiguousFenceWrite("SYNTHETIC_FUGLE_FENCE_AMBIGUOUS_AFTER_CREATE")


def consume_fugle_single_live_fence(
    authorization_review: Mapping[str, Any],
    store: SyntheticWriteOnceFenceStore,
    *,
    expected_authorization_review_sha256: str,
    expected_main_sha: str,
) -> dict[str, Any]:
    auth_review_hash=_hex64(
        expected_authorization_review_sha256,
        "FUGLE_FENCE_EXPECTED_AUTH_REVIEW_HASH_INVALID",
    )
    main=_hex40(expected_main_sha, "FUGLE_FENCE_EXPECTED_MAIN_SHA_INVALID")

    require(type(store) is SyntheticWriteOnceFenceStore,
            "FUGLE_FENCE_REAL_STORE_FORBIDDEN_IN_CI")
    require(isinstance(authorization_review, Mapping),
            "FUGLE_FENCE_AUTH_REVIEW_INVALID")
    require(canonical_digest(authorization_review)==auth_review_hash,
            "FUGLE_FENCE_AUTH_REVIEW_HASH_MISMATCH")
    require(
        authorization_review.get("artifact")
        == "RATE_FUGLE_SINGLE_LIVE_QUALIFICATION_AUTHORIZATION_QUALIFICATION_V1"
        and authorization_review.get("validation_status")=="PASS",
        "FUGLE_FENCE_AUTH_REVIEW_NOT_PASS",
    )
    require(authorization_review.get("current_main_sha")==main,
            "FUGLE_FENCE_MAIN_BINDING_MISMATCH")
    require(authorization_review.get("single_use") is True
            and authorization_review.get("execution_consumed") is False,
            "FUGLE_FENCE_SINGLE_USE_BOUNDARY_INVALID")
    require(authorization_review.get("request_budget")==30,
            "FUGLE_FENCE_REQUEST_BUDGET_INVALID")
    require(authorization_review.get("automatic_retry_allowed") is False
            and authorization_review.get("fallback_allowed") is False
            and authorization_review.get("redirect_allowed") is False,
            "FUGLE_FENCE_NETWORK_BOUNDARY_INVALID")

    key=fence_key(authorization_review["authorization_sha256"])
    existing=store.read(key)
    if existing is not None:
        require(existing.get("state")=="CONSUMED_BEFORE_CREDENTIAL_OR_NETWORK",
                "FUGLE_FENCE_EXISTING_STATE_INVALID")
        require(existing.get("main_sha")==main,
                "FUGLE_FENCE_EXISTING_MAIN_CONFLICT")
        require(existing.get("authorization_review_sha256")==auth_review_hash,
                "FUGLE_FENCE_EXISTING_AUTH_CONFLICT")
        raise FugleConsumptionFenceError("FUGLE_FENCE_ALREADY_CONSUMED")

    receipt={
        "artifact":"RATE_FUGLE_SINGLE_LIVE_CONSUMPTION_RECEIPT_V1",
        "state":"CONSUMED_BEFORE_CREDENTIAL_OR_NETWORK",
        "authorization_review_sha256":auth_review_hash,
        "authorization_sha256":authorization_review["authorization_sha256"],
        "main_sha":main,
        "provider":"Fugle",
        "cadence":authorization_review["cadence"],
        "request_budget":30,
        "credential_access_before_receipt":0,
        "provider_requests_before_receipt":0,
        "retry_allowed":False,
        "fallback_allowed":False,
        "redirect_allowed":False,
    }
    receipt["receipt_sha256"]=canonical_digest(receipt)

    try:
        store.create_once(key,receipt)
    except AmbiguousFenceWrite:
        persisted=store.read(key)
        require(persisted is not None, "FUGLE_FENCE_AMBIGUOUS_WRITE_UNRESOLVED")
        require(persisted==receipt, "FUGLE_FENCE_AMBIGUOUS_WRITE_CONFLICT")
        outcome="AMBIGUOUS_CREATE_CONFIRMED_BY_READBACK"
    else:
        persisted=store.read(key)
        require(persisted==receipt, "FUGLE_FENCE_READBACK_MISMATCH")
        outcome="CREATED_AND_READBACK_VERIFIED"

    require(store.write_attempts==1, "FUGLE_FENCE_WRITE_BUDGET_INVALID")
    require(store.update_attempts==0 and store.delete_attempts==0,
            "FUGLE_FENCE_MUTATION_BUDGET_INVALID")

    return {
        "artifact":"RATE_FUGLE_SINGLE_LIVE_CONSUMPTION_FENCE_V1",
        "validation_status":"PASS",
        "outcome":outcome,
        "fence_key":key,
        "receipt_sha256":receipt["receipt_sha256"],
        "authorization_review_sha256":auth_review_hash,
        "authorization_sha256":authorization_review["authorization_sha256"],
        "main_sha":main,
        "cadence":authorization_review["cadence"],
        "request_budget":30,
        "write_attempts":1,
        "write_retries":0,
        "readback_verified":True,
        "credential_access_before_receipt":0,
        "provider_requests_before_receipt":0,
        "real_store_writes":0,
        "credential_access":0,
        "live_provider_requests":0,
        "production_activation_allowed":False,
        "external_dependency_resolved":False,
        "production_credit":0,
        "cer081_credit":0,
        "next_gate":"AUTHORIZED_FUGLE_SINGLE_LIVE_EXECUTOR_ORCHESTRATION"
    }

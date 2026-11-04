"""Synthetic rehearsal for the durable Git-ref consumption marker used by Cloudflare qualification."""
from __future__ import annotations

from copy import deepcopy
import re
from typing import Any, Mapping

from .intraday_activation_candidate_review import canonical_digest
from .intraday_cloudflare_d1_real_qualification_plan import EXPECTED_CONSUMPTION_MARKER

HEX40=re.compile(r"^[0-9a-f]{40}$")
HEX64=re.compile(r"^[0-9a-f]{64}$")


class MarkerRehearsalError(RuntimeError):
    pass


class AmbiguousMarkerCreate(RuntimeError):
    pass


def require(condition: bool, reason: str) -> None:
    if not condition:
        raise MarkerRehearsalError(reason)


def _sha40(value: Any, reason: str) -> str:
    text=str(value or "").lower()
    require(bool(HEX40.fullmatch(text)),reason)
    return text


def _sha64(value: Any, reason: str) -> str:
    text=str(value or "").lower()
    require(bool(HEX64.fullmatch(text)),reason)
    return text


def marker_ref_for(authorization_hash: str) -> str:
    value=_sha64(authorization_hash,"CF_MARKER_AUTH_HASH_INVALID")
    return (
        EXPECTED_CONSUMPTION_MARKER["ref_prefix"]
        + value[:EXPECTED_CONSUMPTION_MARKER["hash_prefix_hex_chars"]]
    )


class SyntheticGitRefBackend:
    backend="SYNTHETIC_GIT_REF_BACKEND"

    def __init__(self, *, main_sha: str, fail_mode: str|None=None):
        self.main_sha=main_sha
        self.fail_mode=fail_mode
        self.refs: dict[str,str]={}
        self.create_attempts=0
        self.read_attempts=0
        self.update_attempts=0
        self.delete_attempts=0

    def read_ref(self, ref: str):
        self.read_attempts += 1
        return self.refs.get(ref)

    def create_ref(self, ref: str, target_sha: str):
        self.create_attempts += 1
        if self.fail_mode=="BEFORE_CREATE":
            raise RuntimeError("SYNTHETIC_MARKER_FAIL_BEFORE_CREATE")
        require(ref not in self.refs,"CF_MARKER_ALREADY_CONSUMED")
        self.refs[ref]=target_sha
        if self.fail_mode=="AMBIGUOUS_AFTER_CREATE":
            raise AmbiguousMarkerCreate("SYNTHETIC_MARKER_AMBIGUOUS_AFTER_CREATE")


def rehearse_consumption_marker(
    authorization_qualification: Mapping[str,Any],
    backend: SyntheticGitRefBackend,
    *,
    expected_authorization_qualification_sha256: str,
    expected_current_main_sha: str,
) -> dict[str,Any]:
    require(
        type(backend) is SyntheticGitRefBackend
        and backend.backend=="SYNTHETIC_GIT_REF_BACKEND",
        "CF_MARKER_REAL_BACKEND_FORBIDDEN",
    )
    auth_hash=_sha64(
        expected_authorization_qualification_sha256,
        "CF_MARKER_EXPECTED_AUTH_HASH_INVALID",
    )
    main_sha=_sha40(expected_current_main_sha,"CF_MARKER_EXPECTED_MAIN_INVALID")
    require(isinstance(authorization_qualification,Mapping),"CF_MARKER_QUALIFICATION_INVALID")
    require(
        canonical_digest(authorization_qualification)==auth_hash,
        "CF_MARKER_QUALIFICATION_HASH_MISMATCH",
    )
    require(
        authorization_qualification.get("artifact")
        =="RATE_CLOUDFLARE_D1_REAL_PROVIDER_QUALIFICATION_AUTHORIZATION_QUALIFICATION_V1"
        and authorization_qualification.get("validation_status")=="PASS",
        "CF_MARKER_QUALIFICATION_NOT_PASS",
    )
    require(
        authorization_qualification.get("current_main_sha")==main_sha,
        "CF_MARKER_MAIN_BINDING_MISMATCH",
    )
    require(
        authorization_qualification.get("consumption_marker")==EXPECTED_CONSUMPTION_MARKER,
        "CF_MARKER_CONTRACT_MISMATCH",
    )
    require(
        authorization_qualification.get("single_use") is True
        and authorization_qualification.get("execution_consumed") is False,
        "CF_MARKER_SINGLE_USE_BOUNDARY_INVALID",
    )
    require(backend.main_sha==main_sha,"CF_MARKER_BACKEND_MAIN_MISMATCH")

    ref=marker_ref_for(auth_hash)
    existing=backend.read_ref(ref)
    if existing is not None:
        require(existing==main_sha,"CF_MARKER_EXISTING_TARGET_CONFLICT")
        raise MarkerRehearsalError("CF_MARKER_ALREADY_CONSUMED")

    try:
        backend.create_ref(ref,main_sha)
    except AmbiguousMarkerCreate:
        persisted=backend.read_ref(ref)
        require(persisted is not None,"CF_MARKER_AMBIGUOUS_CREATE_UNRESOLVED")
        require(persisted==main_sha,"CF_MARKER_AMBIGUOUS_TARGET_CONFLICT")
        outcome="AMBIGUOUS_CREATE_CONFIRMED_BY_READBACK"
    else:
        persisted=backend.read_ref(ref)
        require(persisted==main_sha,"CF_MARKER_READBACK_MISMATCH")
        outcome="CREATED_AND_READBACK_VERIFIED"

    require(backend.create_attempts==1,"CF_MARKER_CREATE_BUDGET_INVALID")
    require(backend.update_attempts==0 and backend.delete_attempts==0,
            "CF_MARKER_MUTATION_BUDGET_INVALID")
    return {
        "artifact":"RATE_CLOUDFLARE_D1_QUALIFICATION_CONSUMPTION_MARKER_REHEARSAL_V1",
        "validation_status":"PASS",
        "outcome":outcome,
        "marker_ref":ref,
        "marker_target_sha":main_sha,
        "authorization_qualification_sha256":auth_hash,
        "create_attempts":backend.create_attempts,
        "read_attempts":backend.read_attempts,
        "create_retries":0,
        "update_attempts":0,
        "delete_attempts":0,
        "cloudflare_requests_before_marker":0,
        "real_git_ref_created":False,
        "real_cloudflare_requests":0,
        "provider_qualified":False,
        "production_credit":0,
        "cer081_credit":0,
        "next_gate":"REAL_GITHUB_REF_MARKER_ADAPTER_QUALIFICATION",
    }

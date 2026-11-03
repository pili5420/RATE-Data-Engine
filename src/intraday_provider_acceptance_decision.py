"""Deterministic builder for a future Control Center provider-acceptance decision.

The builder is packaging only. It does not independently authorize provider
acceptance and does not create the external expected decision hash used by the
provider-acceptance validator.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import re
from typing import Any, Mapping

HEX40 = re.compile(r"^[0-9a-f]{40}$")
ALLOWED_LICENSE_BASES = {"OWNER_ASSUMED_AUTHORIZED", "PROVIDER_WRITTEN_CONFIRMED"}
REQUIRED_MARKETS = ["TWSE", "TPEX"]
REQUIRED_CADENCES = ["09:30", "12:00"]


class ProviderAcceptanceDecisionBuildError(RuntimeError):
    pass


def require(condition: bool, reason: str) -> None:
    if not condition:
        raise ProviderAcceptanceDecisionBuildError(reason)


def canonical_digest(value: Mapping[str, Any], *, omit: set[str] | None = None) -> str:
    omit = omit or set()
    body = {k: v for k, v in value.items() if k not in omit}
    return hashlib.sha256(
        json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _sha40(value: Any, reason: str) -> str:
    text = str(value or "").lower()
    require(bool(HEX40.fullmatch(text)), reason)
    return text


def build_provider_acceptance_decision(
    live_review: Mapping[str, Any],
    provider_authority: Mapping[str, Any],
    *,
    main_sha: str,
    control_center_decision_id: str,
    control_center_authorization_status: str,
    provider_name: str,
    license_basis: str,
    provider_written_confirmation: bool,
    credential_secret_name: str,
) -> dict[str, Any]:
    main = _sha40(main_sha, "PROVIDER_DECISION_BUILD_MAIN_SHA_INVALID")
    require(
        isinstance(control_center_decision_id, str) and control_center_decision_id.strip(),
        "PROVIDER_DECISION_BUILD_DECISION_ID_MISSING",
    )
    require(
        control_center_authorization_status == "PROVIDER_ACCEPTANCE_AUTHORIZED",
        "PROVIDER_DECISION_BUILD_CONTROL_CENTER_AUTHORIZATION_REQUIRED",
    )
    require(isinstance(provider_name, str) and provider_name.strip(),
            "PROVIDER_DECISION_BUILD_PROVIDER_INVALID")
    require(license_basis in ALLOWED_LICENSE_BASES,
            "PROVIDER_DECISION_BUILD_LICENSE_BASIS_INVALID")
    require(isinstance(provider_written_confirmation, bool),
            "PROVIDER_DECISION_BUILD_WRITTEN_CONFIRMATION_FLAG_INVALID")
    require(
        (license_basis == "PROVIDER_WRITTEN_CONFIRMED" and provider_written_confirmation is True)
        or (license_basis == "OWNER_ASSUMED_AUTHORIZED" and provider_written_confirmation is False),
        "PROVIDER_DECISION_BUILD_LICENSE_EVIDENCE_CONTRADICTION",
    )
    require(isinstance(credential_secret_name, str) and credential_secret_name.strip(),
            "PROVIDER_DECISION_BUILD_SECRET_NAME_MISSING")

    require(isinstance(live_review, Mapping), "PROVIDER_DECISION_BUILD_LIVE_REVIEW_INVALID")
    require(
        live_review.get("artifact") == "RATE_INTRADAY_SINGLE_LIVE_QUALIFICATION_REVIEW_V1"
        and live_review.get("validation_status") == "PASS"
        and live_review.get("review_disposition") == "READY_FOR_CONTROL_CENTER_PROVIDER_ACCEPTANCE",
        "PROVIDER_DECISION_BUILD_LIVE_REVIEW_NOT_PASS",
    )
    require(live_review.get("provider_name") == provider_name,
            "PROVIDER_DECISION_BUILD_LIVE_REVIEW_PROVIDER_MISMATCH")
    require(live_review.get("provider_accepted") is False
            and live_review.get("activation_execution_allowed") is False
            and live_review.get("external_dependency_resolved") is False
            and live_review.get("production_credit") == 0
            and live_review.get("cer081_credit") == 0,
            "PROVIDER_DECISION_BUILD_LIVE_REVIEW_PREMATURE_STATE")

    require(isinstance(provider_authority, Mapping),
            "PROVIDER_DECISION_BUILD_AUTHORITY_INVALID")
    require(
        provider_authority.get("artifact") == "RATE_INTRADAY_PROVIDER_AUTHORITY_QUALIFICATION_V1"
        and provider_authority.get("validation_status") == "PASS",
        "PROVIDER_DECISION_BUILD_AUTHORITY_NOT_PASS",
    )
    require(provider_authority.get("provider_name") == provider_name,
            "PROVIDER_DECISION_BUILD_AUTHORITY_PROVIDER_MISMATCH")
    require(provider_authority.get("production_activation_allowed") is False,
            "PROVIDER_DECISION_BUILD_AUTHORITY_PREMATURE_STATE")

    review_copy = deepcopy(dict(live_review))
    review_hash = canonical_digest(review_copy, omit={"sha256"})
    review_copy["sha256"] = review_hash

    authority_copy = deepcopy(dict(provider_authority))

    decision = {
        "artifact": "RATE_INTRADAY_PROVIDER_ACCEPTANCE_DECISION_V1",
        "status": "PROVIDER_ACCEPTANCE_AUTHORIZED",
        "control_center_decision_id": control_center_decision_id,
        "main_sha": main,
        "provider_name": provider_name,
        "license_basis": license_basis,
        "usage_scope": {
            "personal_internal_only": True,
            "public_display": False,
            "raw_data_redistribution": False,
            "resale": False,
            "sublicensing": False,
            "third_party_market_data_feed": False,
            "provider_written_confirmation": provider_written_confirmation,
        },
        "live_review": review_copy,
        "provider_authority": authority_copy,
        "target": {
            "external_dependency_id": "EXTERNAL_AUTHORIZED_INTRADAY_FEED_DEPENDENCY",
            "source_registry_dataset_id": "authorized_market_intraday",
            "required_markets": list(REQUIRED_MARKETS),
            "authorized_cadences": list(REQUIRED_CADENCES),
        },
        "credential_boundary": {
            "store": "GITHUB_ACTIONS_SECRET",
            "secret_name": credential_secret_name,
            "secret_value_embedded": False,
        },
        "fallback_allowed": False,
        "automatic_retry_allowed": False,
        "activation_execution_allowed": False,
        "external_dependency_resolved": False,
        "registry_activation_allowed": False,
        "production_credit": 0,
        "cer081_credit": 0,
    }
    decision["decision_sha256"] = canonical_digest(decision)

    return {
        "artifact": "RATE_INTRADAY_PROVIDER_ACCEPTANCE_DECISION_PACKAGE_V1",
        "builder_disposition": "NOT_A_CONTROL_CENTER_DECISION",
        "control_center_authorization_status_input": control_center_authorization_status,
        "live_review_sha256": review_hash,
        "decision_sha256": decision["decision_sha256"],
        "decision": decision,
        "network_requests": 0,
        "credential_access": 0,
        "registry_mutations": 0,
        "scheduler_mutations": 0,
        "production_state_mutations": 0,
        "production_credit": 0,
        "cer081_credit": 0,
    }

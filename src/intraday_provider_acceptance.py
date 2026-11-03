"""Pure Control Center gate for accepting an intraday provider after live review.

A PASS accepts the provider for the next activation-design stage only. It never
mutates registry/scheduler state, never resolves the external dependency, never
reads credentials, and never authorizes Production execution.
"""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Mapping

HEX40 = re.compile(r"^[0-9a-f]{40}$")
HEX64 = re.compile(r"^[0-9a-f]{64}$")
REQUIRED_MARKETS = {"TWSE", "TPEX"}
REQUIRED_CADENCES = {"09:30", "12:00"}
REQUIRED_MARKET_COUNTS = {"TWSE": 25, "TPEX": 5}
DEPENDENCY_ID = "EXTERNAL_AUTHORIZED_INTRADAY_FEED_DEPENDENCY"
DATASET_ID = "authorized_market_intraday"
ALLOWED_LICENSE_BASES = {"OWNER_ASSUMED_AUTHORIZED", "PROVIDER_WRITTEN_CONFIRMED"}


class ProviderAcceptanceError(RuntimeError):
    pass


def require(condition: bool, reason: str) -> None:
    if not condition:
        raise ProviderAcceptanceError(reason)


def canonical_digest(value: Mapping[str, Any], *, omit: set[str] | None = None) -> str:
    omit = omit or set()
    body = {k: v for k, v in value.items() if k not in omit}
    return hashlib.sha256(
        json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _hex40(value: Any, reason: str) -> str:
    text = str(value or "").lower()
    require(bool(HEX40.fullmatch(text)), reason)
    return text


def _hex64(value: Any, reason: str) -> str:
    text = str(value or "").lower()
    require(bool(HEX64.fullmatch(text)), reason)
    return text


def _market_counts(value: Any, reason: str) -> None:
    require(isinstance(value, Mapping) and set(value) == REQUIRED_MARKETS, reason)
    require(all(isinstance(v, int) and not isinstance(v, bool) for v in value.values()), reason)
    require(dict(value) == REQUIRED_MARKET_COUNTS, reason)


def validate_provider_acceptance(
    decision: Mapping[str, Any],
    *,
    expected_main_sha: str,
    expected_control_center_decision_id: str,
    expected_decision_sha256: str,
    expected_provider_name: str,
    expected_live_review_sha256: str,
    expected_provider_authority_binding_sha256: str,
    expected_license_basis: str,
) -> dict[str, Any]:
    main_sha = _hex40(expected_main_sha, "PROVIDER_ACCEPTANCE_EXPECTED_MAIN_SHA_INVALID")
    require(
        isinstance(expected_control_center_decision_id, str)
        and expected_control_center_decision_id.strip(),
        "PROVIDER_ACCEPTANCE_EXPECTED_DECISION_ID_MISSING",
    )
    expected_decision_hash = _hex64(
        expected_decision_sha256, "PROVIDER_ACCEPTANCE_EXPECTED_DECISION_HASH_INVALID"
    )
    require(
        isinstance(expected_provider_name, str) and expected_provider_name.strip(),
        "PROVIDER_ACCEPTANCE_EXPECTED_PROVIDER_INVALID",
    )
    live_review_hash = _hex64(
        expected_live_review_sha256, "PROVIDER_ACCEPTANCE_EXPECTED_LIVE_REVIEW_HASH_INVALID"
    )
    authority_hash = _hex64(
        expected_provider_authority_binding_sha256,
        "PROVIDER_ACCEPTANCE_EXPECTED_AUTHORITY_HASH_INVALID",
    )
    require(expected_license_basis in ALLOWED_LICENSE_BASES,
            "PROVIDER_ACCEPTANCE_EXPECTED_LICENSE_BASIS_INVALID")

    require(isinstance(decision, Mapping), "PROVIDER_ACCEPTANCE_DECISION_INVALID")
    require(
        decision.get("artifact") == "RATE_INTRADAY_PROVIDER_ACCEPTANCE_DECISION_V1",
        "PROVIDER_ACCEPTANCE_ARTIFACT_INVALID",
    )
    require(decision.get("status") == "PROVIDER_ACCEPTANCE_AUTHORIZED",
            "PROVIDER_ACCEPTANCE_STATUS_INVALID")
    require(decision.get("control_center_decision_id") == expected_control_center_decision_id,
            "PROVIDER_ACCEPTANCE_DECISION_ID_MISMATCH")
    require(_hex40(decision.get("main_sha"), "PROVIDER_ACCEPTANCE_MAIN_SHA_INVALID") == main_sha,
            "PROVIDER_ACCEPTANCE_MAIN_SHA_MISMATCH")
    require(decision.get("provider_name") == expected_provider_name,
            "PROVIDER_ACCEPTANCE_PROVIDER_MISMATCH")
    require(decision.get("license_basis") == expected_license_basis,
            "PROVIDER_ACCEPTANCE_LICENSE_BASIS_MISMATCH")

    identity = _hex64(decision.get("decision_sha256"), "PROVIDER_ACCEPTANCE_DECISION_HASH_INVALID")
    require(identity == canonical_digest(decision, omit={"decision_sha256"}),
            "PROVIDER_ACCEPTANCE_DECISION_SELF_HASH_MISMATCH")
    require(identity == expected_decision_hash,
            "PROVIDER_ACCEPTANCE_EXPECTED_DECISION_HASH_MISMATCH")

    usage = decision.get("usage_scope")
    require(isinstance(usage, Mapping), "PROVIDER_ACCEPTANCE_USAGE_SCOPE_MISSING")
    require(
        usage.get("personal_internal_only") is True
        and usage.get("public_display") is False
        and usage.get("raw_data_redistribution") is False
        and usage.get("resale") is False
        and usage.get("sublicensing") is False
        and usage.get("third_party_market_data_feed") is False,
        "PROVIDER_ACCEPTANCE_USAGE_SCOPE_INVALID",
    )
    if expected_license_basis == "OWNER_ASSUMED_AUTHORIZED":
        require(usage.get("provider_written_confirmation") is False,
                "PROVIDER_ACCEPTANCE_LICENSE_EVIDENCE_CONTRADICTION")

    review = decision.get("live_review")
    require(isinstance(review, Mapping), "PROVIDER_ACCEPTANCE_LIVE_REVIEW_MISSING")
    require(
        review.get("artifact") == "RATE_INTRADAY_SINGLE_LIVE_QUALIFICATION_REVIEW_V1"
        and review.get("validation_status") == "PASS"
        and review.get("review_disposition") == "READY_FOR_CONTROL_CENTER_PROVIDER_ACCEPTANCE",
        "PROVIDER_ACCEPTANCE_LIVE_REVIEW_NOT_PASS",
    )
    require(_hex64(review.get("sha256"), "PROVIDER_ACCEPTANCE_LIVE_REVIEW_HASH_INVALID") == live_review_hash,
            "PROVIDER_ACCEPTANCE_LIVE_REVIEW_HASH_MISMATCH")
    require(review.get("provider_name") == expected_provider_name,
            "PROVIDER_ACCEPTANCE_LIVE_REVIEW_PROVIDER_MISMATCH")
    require(review.get("market_coverage") == "30/30",
            "PROVIDER_ACCEPTANCE_LIVE_REVIEW_COVERAGE_INVALID")
    _market_counts(review.get("market_counts"), "PROVIDER_ACCEPTANCE_LIVE_REVIEW_MARKET_COUNTS_INVALID")
    require(
        review.get("network_requests") == 30
        and review.get("http_redirects_followed") == 0
        and review.get("automatic_retries") == 0
        and review.get("fallback_used") is False
        and review.get("secret_exposure") is False,
        "PROVIDER_ACCEPTANCE_LIVE_REVIEW_RUNTIME_BOUNDARY_INVALID",
    )
    require(
        review.get("provider_accepted") is False
        and review.get("activation_execution_allowed") is False
        and review.get("external_dependency_resolved") is False
        and review.get("production_credit") == 0
        and review.get("cer081_credit") == 0,
        "PROVIDER_ACCEPTANCE_LIVE_REVIEW_PREMATURE_STATE",
    )

    authority = decision.get("provider_authority")
    require(isinstance(authority, Mapping), "PROVIDER_ACCEPTANCE_AUTHORITY_MISSING")
    require(
        authority.get("artifact") == "RATE_INTRADAY_PROVIDER_AUTHORITY_QUALIFICATION_V1"
        and authority.get("validation_status") == "PASS",
        "PROVIDER_ACCEPTANCE_AUTHORITY_NOT_PASS",
    )
    require(
        _hex64(authority.get("authority_binding_sha256"),
               "PROVIDER_ACCEPTANCE_AUTHORITY_HASH_INVALID") == authority_hash,
        "PROVIDER_ACCEPTANCE_AUTHORITY_HASH_MISMATCH",
    )
    require(authority.get("provider_name") == expected_provider_name,
            "PROVIDER_ACCEPTANCE_AUTHORITY_PROVIDER_MISMATCH")
    require(set(authority.get("required_markets", [])) == REQUIRED_MARKETS
            and set(authority.get("market_coverage", [])) == REQUIRED_MARKETS,
            "PROVIDER_ACCEPTANCE_AUTHORITY_MARKETS_INVALID")
    require(
        authority.get("automated_non_display_use") is True
        and authority.get("internal_use_only") is True
        and authority.get("fallback_allowed") is False
        and authority.get("production_activation_allowed") is False,
        "PROVIDER_ACCEPTANCE_AUTHORITY_USAGE_BOUNDARY_INVALID",
    )

    target = decision.get("target")
    require(isinstance(target, Mapping), "PROVIDER_ACCEPTANCE_TARGET_MISSING")
    require(target.get("external_dependency_id") == DEPENDENCY_ID,
            "PROVIDER_ACCEPTANCE_TARGET_DEPENDENCY_INVALID")
    require(target.get("source_registry_dataset_id") == DATASET_ID,
            "PROVIDER_ACCEPTANCE_TARGET_DATASET_INVALID")
    require(set(target.get("required_markets", [])) == REQUIRED_MARKETS,
            "PROVIDER_ACCEPTANCE_TARGET_MARKETS_INVALID")
    require(set(target.get("authorized_cadences", [])) == REQUIRED_CADENCES,
            "PROVIDER_ACCEPTANCE_TARGET_CADENCES_INVALID")

    credential = decision.get("credential_boundary")
    require(isinstance(credential, Mapping), "PROVIDER_ACCEPTANCE_CREDENTIAL_BOUNDARY_MISSING")
    require(credential.get("store") == "GITHUB_ACTIONS_SECRET",
            "PROVIDER_ACCEPTANCE_CREDENTIAL_STORE_INVALID")
    require(isinstance(credential.get("secret_name"), str) and credential["secret_name"].strip(),
            "PROVIDER_ACCEPTANCE_SECRET_NAME_MISSING")
    require(credential.get("secret_value_embedded") is False,
            "PROVIDER_ACCEPTANCE_SECRET_VALUE_FORBIDDEN")

    require(
        decision.get("fallback_allowed") is False
        and decision.get("automatic_retry_allowed") is False
        and decision.get("activation_execution_allowed") is False
        and decision.get("external_dependency_resolved") is False
        and decision.get("registry_activation_allowed") is False
        and decision.get("production_credit") == 0
        and decision.get("cer081_credit") == 0,
        "PROVIDER_ACCEPTANCE_PREMATURE_PRODUCTION_STATE",
    )

    return {
        "artifact": "RATE_INTRADAY_PROVIDER_ACCEPTANCE_V1",
        "validation_status": "PASS",
        "control_center_decision_id": expected_control_center_decision_id,
        "decision_sha256": identity,
        "main_sha": main_sha,
        "provider_name": expected_provider_name,
        "license_basis": expected_license_basis,
        "provider_accepted": True,
        "required_markets": sorted(REQUIRED_MARKETS),
        "authorized_cadences": sorted(REQUIRED_CADENCES),
        "external_dependency_id": DEPENDENCY_ID,
        "source_registry_dataset_id": DATASET_ID,
        "fallback_allowed": False,
        "automatic_retry_allowed": False,
        "activation_execution_allowed": False,
        "external_dependency_resolved": False,
        "registry_activation_allowed": False,
        "network_requests": 0,
        "credential_access": 0,
        "registry_mutations": 0,
        "scheduler_mutations": 0,
        "production_state_mutations": 0,
        "production_credit": 0,
        "cer081_credit": 0,
        "next_gate": "SEPARATE_CONTROL_CENTER_ACTIVATION_IMPLEMENTATION",
    }

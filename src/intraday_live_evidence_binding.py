"""Bind real single-live qualification evidence to one reviewed activation candidate.

This gate is pure. It never applies the candidate. It preserves the exact cadence
scope of the live evidence and requires a final-main rebase before any activation
apply decision.
"""
from __future__ import annotations

from typing import Any, Mapping
import re

from .intraday_activation_candidate_review import canonical_digest

HEX40 = re.compile(r"^[0-9a-f]{40}$")
HEX64 = re.compile(r"^[0-9a-f]{64}$")
REQUIRED_MARKETS = {"TWSE", "TPEX"}
REQUIRED_MARKET_COUNTS = {"TWSE": 25, "TPEX": 5}
ALL_CADENCES = {"09:30", "12:00"}
ALLOWED_LICENSE_BASES = {"OWNER_ASSUMED_AUTHORIZED", "PROVIDER_WRITTEN_CONFIRMED"}


class LiveEvidenceBindingError(RuntimeError):
    pass


def require(condition: bool, reason: str) -> None:
    if not condition:
        raise LiveEvidenceBindingError(reason)


def _sha40(value: Any, reason: str) -> str:
    text = str(value or "").lower()
    require(bool(HEX40.fullmatch(text)), reason)
    return text


def _sha64(value: Any, reason: str) -> str:
    text = str(value or "").lower()
    require(bool(HEX64.fullmatch(text)), reason)
    return text


def _exact_market_counts(value: Any, reason: str) -> None:
    require(
        isinstance(value, Mapping)
        and set(value) == REQUIRED_MARKETS
        and all(isinstance(v, int) and not isinstance(v, bool) for v in value.values())
        and dict(value) == REQUIRED_MARKET_COUNTS,
        reason,
    )


def bind_live_evidence_to_activation_candidate(
    synthetic_review: Mapping[str, Any],
    live_review: Mapping[str, Any],
    provider_acceptance: Mapping[str, Any],
    *,
    expected_synthetic_review_sha256: str,
    expected_live_review_sha256: str,
    expected_provider_acceptance_sha256: str,
    expected_provider_acceptance_decision_sha256: str,
    expected_candidate_manifest_sha256: str,
    expected_candidate_base_main_sha: str,
    expected_provider_name: str,
    expected_live_cadence: str,
    expected_license_basis: str,
) -> dict[str, Any]:
    synthetic_hash = _sha64(
        expected_synthetic_review_sha256,
        "LIVE_BINDING_EXPECTED_SYNTHETIC_REVIEW_HASH_INVALID",
    )
    live_hash = _sha64(
        expected_live_review_sha256,
        "LIVE_BINDING_EXPECTED_LIVE_REVIEW_HASH_INVALID",
    )
    acceptance_hash = _sha64(
        expected_provider_acceptance_sha256,
        "LIVE_BINDING_EXPECTED_PROVIDER_ACCEPTANCE_HASH_INVALID",
    )
    acceptance_decision_hash = _sha64(
        expected_provider_acceptance_decision_sha256,
        "LIVE_BINDING_EXPECTED_PROVIDER_DECISION_HASH_INVALID",
    )
    candidate_manifest_hash = _sha64(
        expected_candidate_manifest_sha256,
        "LIVE_BINDING_EXPECTED_CANDIDATE_MANIFEST_HASH_INVALID",
    )
    candidate_main = _sha40(
        expected_candidate_base_main_sha,
        "LIVE_BINDING_EXPECTED_CANDIDATE_MAIN_INVALID",
    )
    require(
        isinstance(expected_provider_name, str) and expected_provider_name.strip(),
        "LIVE_BINDING_EXPECTED_PROVIDER_INVALID",
    )
    require(expected_live_cadence in ALL_CADENCES,
            "LIVE_BINDING_EXPECTED_LIVE_CADENCE_INVALID")
    require(expected_license_basis in ALLOWED_LICENSE_BASES,
            "LIVE_BINDING_EXPECTED_LICENSE_BASIS_INVALID")

    require(isinstance(synthetic_review, Mapping), "LIVE_BINDING_SYNTHETIC_REVIEW_INVALID")
    require(
        canonical_digest(synthetic_review) == synthetic_hash,
        "LIVE_BINDING_SYNTHETIC_REVIEW_HASH_MISMATCH",
    )
    require(
        synthetic_review.get("artifact")
        == "RATE_INTRADAY_FULL_SYNTHETIC_ACTIVATION_CANDIDATE_REVIEW_V1"
        and synthetic_review.get("validation_status") == "PASS"
        and synthetic_review.get("review_disposition")
        == "READY_FOR_LIVE_EVIDENCE_BOUND_ACTIVATION_REVIEW",
        "LIVE_BINDING_SYNTHETIC_REVIEW_NOT_PASS",
    )
    require(synthetic_review.get("main_sha") == candidate_main,
            "LIVE_BINDING_CANDIDATE_MAIN_MISMATCH")
    require(synthetic_review.get("provider_name") == expected_provider_name,
            "LIVE_BINDING_SYNTHETIC_PROVIDER_MISMATCH")
    require(synthetic_review.get("cadence") == expected_live_cadence,
            "LIVE_BINDING_SYNTHETIC_CADENCE_MISMATCH")
    require(
        synthetic_review.get("candidate_manifest_sha256") == candidate_manifest_hash,
        "LIVE_BINDING_CANDIDATE_MANIFEST_HASH_MISMATCH",
    )
    require(
        synthetic_review.get("coverage") == "30/30"
        and synthetic_review.get("market_counts") == REQUIRED_MARKET_COUNTS
        and synthetic_review.get("real_network_requests") == 0
        and synthetic_review.get("provider_accepted") is False
        and synthetic_review.get("activation_execution_allowed") is False
        and synthetic_review.get("external_dependency_resolved") is False
        and synthetic_review.get("registry_activation_allowed") is False
        and synthetic_review.get("production_credit") == 0
        and synthetic_review.get("cer081_credit") == 0,
        "LIVE_BINDING_SYNTHETIC_BOUNDARY_INVALID",
    )

    require(isinstance(live_review, Mapping), "LIVE_BINDING_LIVE_REVIEW_INVALID")
    require(
        canonical_digest(live_review) == live_hash,
        "LIVE_BINDING_LIVE_REVIEW_HASH_MISMATCH",
    )
    require(
        live_review.get("artifact")
        == "RATE_INTRADAY_SINGLE_LIVE_QUALIFICATION_REVIEW_V1"
        and live_review.get("validation_status") == "PASS"
        and live_review.get("review_disposition")
        == "READY_FOR_CONTROL_CENTER_PROVIDER_ACCEPTANCE",
        "LIVE_BINDING_LIVE_REVIEW_NOT_PASS",
    )
    require(live_review.get("provider_name") == expected_provider_name,
            "LIVE_BINDING_LIVE_PROVIDER_MISMATCH")
    require(live_review.get("cadence") == expected_live_cadence,
            "LIVE_BINDING_LIVE_CADENCE_MISMATCH")
    require(live_review.get("market_coverage") == "30/30",
            "LIVE_BINDING_LIVE_COVERAGE_INVALID")
    _exact_market_counts(
        live_review.get("market_counts"),
        "LIVE_BINDING_LIVE_MARKET_COUNTS_INVALID",
    )
    require(
        live_review.get("network_requests") == 30
        and live_review.get("http_redirects_followed") == 0
        and live_review.get("automatic_retries") == 0
        and live_review.get("fallback_used") is False
        and live_review.get("secret_exposure") is False,
        "LIVE_BINDING_LIVE_RUNTIME_BOUNDARY_INVALID",
    )
    require(
        live_review.get("provider_accepted") is False
        and live_review.get("activation_execution_allowed") is False
        and live_review.get("external_dependency_resolved") is False
        and live_review.get("production_credit") == 0
        and live_review.get("cer081_credit") == 0,
        "LIVE_BINDING_LIVE_PREMATURE_STATE",
    )

    require(
        isinstance(provider_acceptance, Mapping),
        "LIVE_BINDING_PROVIDER_ACCEPTANCE_INVALID",
    )
    require(
        canonical_digest(provider_acceptance) == acceptance_hash,
        "LIVE_BINDING_PROVIDER_ACCEPTANCE_HASH_MISMATCH",
    )
    require(
        provider_acceptance.get("artifact") == "RATE_INTRADAY_PROVIDER_ACCEPTANCE_V1"
        and provider_acceptance.get("validation_status") == "PASS"
        and provider_acceptance.get("provider_accepted") is True,
        "LIVE_BINDING_PROVIDER_ACCEPTANCE_NOT_PASS",
    )
    require(
        provider_acceptance.get("decision_sha256") == acceptance_decision_hash,
        "LIVE_BINDING_PROVIDER_DECISION_HASH_MISMATCH",
    )
    require(provider_acceptance.get("provider_name") == expected_provider_name,
            "LIVE_BINDING_ACCEPTANCE_PROVIDER_MISMATCH")
    require(provider_acceptance.get("license_basis") == expected_license_basis,
            "LIVE_BINDING_LICENSE_BASIS_MISMATCH")
    require(
        set(provider_acceptance.get("required_markets", [])) == REQUIRED_MARKETS
        and set(provider_acceptance.get("authorized_cadences", [])) == ALL_CADENCES,
        "LIVE_BINDING_PROVIDER_SCOPE_INVALID",
    )
    require(
        provider_acceptance.get("fallback_allowed") is False
        and provider_acceptance.get("automatic_retry_allowed") is False
        and provider_acceptance.get("activation_execution_allowed") is False
        and provider_acceptance.get("external_dependency_resolved") is False
        and provider_acceptance.get("registry_activation_allowed") is False
        and provider_acceptance.get("network_requests") == 0
        and provider_acceptance.get("credential_access") == 0
        and provider_acceptance.get("registry_mutations") == 0
        and provider_acceptance.get("scheduler_mutations") == 0
        and provider_acceptance.get("production_state_mutations") == 0
        and provider_acceptance.get("production_credit") == 0
        and provider_acceptance.get("cer081_credit") == 0,
        "LIVE_BINDING_PROVIDER_ACCEPTANCE_BOUNDARY_INVALID",
    )

    untested = sorted(ALL_CADENCES - {expected_live_cadence})
    return {
        "artifact": "RATE_INTRADAY_LIVE_EVIDENCE_BINDING_V1",
        "validation_status": "PASS",
        "binding_status": "LIVE_EVIDENCE_BOUND",
        "provider_name": expected_provider_name,
        "license_basis": expected_license_basis,
        "candidate_base_main_sha": candidate_main,
        "candidate_manifest_sha256": candidate_manifest_hash,
        "synthetic_review_sha256": synthetic_hash,
        "live_review_sha256": live_hash,
        "provider_acceptance_sha256": acceptance_hash,
        "provider_acceptance_decision_sha256": acceptance_decision_hash,
        "live_evidence_cadences": [expected_live_cadence],
        "authorized_provider_cadences": sorted(ALL_CADENCES),
        "live_untested_cadences": untested,
        "coverage": "30/30",
        "market_counts": dict(REQUIRED_MARKET_COUNTS),
        "final_main_rebase_required": True,
        "provider_accepted": True,
        "apply_allowed": False,
        "activation_execution_allowed": False,
        "external_dependency_resolved": False,
        "registry_activation_allowed": False,
        "production_credit": 0,
        "cer081_credit": 0,
        "next_gate": "FINAL_MAIN_REBASE_AND_ACTIVATION_APPLY_REVIEW",
    }

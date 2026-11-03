"""Final-main activation apply-readiness review for RATE intraday activation.

This gate preserves historical live/provider evidence and separately validates a
fresh current-main delta plan + full synthetic review. It never rewrites old
evidence and never applies candidate files.
"""
from __future__ import annotations

import re
from typing import Any, Mapping

from .intraday_activation_candidate_review import canonical_digest
from .intraday_activation_delta_plan import NEW_RUNTIME_FILES
from .intraday_activation_readiness import (
    ALLOWED_EXISTING_MUTATION_PATHS,
    repo_preimage_hashes,
)

HEX40 = re.compile(r"^[0-9a-f]{40}$")
HEX64 = re.compile(r"^[0-9a-f]{64}$")
REQUIRED_MARKETS = {"TWSE", "TPEX"}
REQUIRED_CADENCES = {"09:30", "12:00"}


class FinalMainApplyReadinessError(RuntimeError):
    pass


def require(condition: bool, reason: str) -> None:
    if not condition:
        raise FinalMainApplyReadinessError(reason)


def _sha40(value: Any, reason: str) -> str:
    text = str(value or "").lower()
    require(bool(HEX40.fullmatch(text)), reason)
    return text


def _sha64(value: Any, reason: str) -> str:
    text = str(value or "").lower()
    require(bool(HEX64.fullmatch(text)), reason)
    return text


def review_final_main_activation_apply_readiness(
    live_binding: Mapping[str, Any],
    rebased_delta_plan: Mapping[str, Any],
    rebased_synthetic_review: Mapping[str, Any],
    *,
    expected_live_binding_sha256: str,
    expected_rebased_delta_plan_sha256: str,
    expected_rebased_synthetic_review_sha256: str,
    expected_current_main_sha: str,
    expected_rebased_candidate_manifest_sha256: str,
    expected_provider_name: str,
    expected_license_basis: str,
    expected_endpoint_template: str,
    expected_secret_name: str,
) -> dict[str, Any]:
    live_hash = _sha64(
        expected_live_binding_sha256,
        "FINAL_APPLY_EXPECTED_LIVE_BINDING_HASH_INVALID",
    )
    delta_hash = _sha64(
        expected_rebased_delta_plan_sha256,
        "FINAL_APPLY_EXPECTED_DELTA_PLAN_HASH_INVALID",
    )
    synthetic_hash = _sha64(
        expected_rebased_synthetic_review_sha256,
        "FINAL_APPLY_EXPECTED_SYNTHETIC_REVIEW_HASH_INVALID",
    )
    current_main = _sha40(
        expected_current_main_sha,
        "FINAL_APPLY_EXPECTED_CURRENT_MAIN_INVALID",
    )
    manifest_hash = _sha64(
        expected_rebased_candidate_manifest_sha256,
        "FINAL_APPLY_EXPECTED_CANDIDATE_MANIFEST_HASH_INVALID",
    )
    require(
        isinstance(expected_provider_name, str) and expected_provider_name.strip(),
        "FINAL_APPLY_EXPECTED_PROVIDER_INVALID",
    )
    require(
        isinstance(expected_license_basis, str) and expected_license_basis.strip(),
        "FINAL_APPLY_EXPECTED_LICENSE_BASIS_INVALID",
    )
    require(
        isinstance(expected_endpoint_template, str)
        and expected_endpoint_template.startswith("https://"),
        "FINAL_APPLY_EXPECTED_ENDPOINT_INVALID",
    )
    require(
        isinstance(expected_secret_name, str) and expected_secret_name.strip(),
        "FINAL_APPLY_EXPECTED_SECRET_NAME_INVALID",
    )

    # Historical evidence is immutable and hash-bound as-is.
    require(isinstance(live_binding, Mapping), "FINAL_APPLY_LIVE_BINDING_INVALID")
    require(
        canonical_digest(live_binding) == live_hash,
        "FINAL_APPLY_LIVE_BINDING_HASH_MISMATCH",
    )
    require(
        live_binding.get("artifact") == "RATE_INTRADAY_LIVE_EVIDENCE_BINDING_V1"
        and live_binding.get("validation_status") == "PASS"
        and live_binding.get("binding_status") == "LIVE_EVIDENCE_BOUND"
        and live_binding.get("final_main_rebase_required") is True,
        "FINAL_APPLY_LIVE_BINDING_NOT_PASS",
    )
    require(live_binding.get("provider_name") == expected_provider_name,
            "FINAL_APPLY_LIVE_PROVIDER_MISMATCH")
    require(live_binding.get("license_basis") == expected_license_basis,
            "FINAL_APPLY_LIVE_LICENSE_BASIS_MISMATCH")
    require(
        live_binding.get("provider_accepted") is True
        and live_binding.get("apply_allowed") is False
        and live_binding.get("activation_execution_allowed") is False
        and live_binding.get("external_dependency_resolved") is False
        and live_binding.get("registry_activation_allowed") is False
        and live_binding.get("production_credit") == 0
        and live_binding.get("cer081_credit") == 0,
        "FINAL_APPLY_LIVE_BINDING_PREMATURE_STATE",
    )

    # Current-main delta is fresh engineering evidence, not a mutation of old evidence.
    require(
        isinstance(rebased_delta_plan, Mapping),
        "FINAL_APPLY_REBASED_DELTA_PLAN_INVALID",
    )
    require(
        canonical_digest(rebased_delta_plan) == delta_hash,
        "FINAL_APPLY_REBASED_DELTA_PLAN_HASH_MISMATCH",
    )
    require(
        rebased_delta_plan.get("artifact") == "RATE_INTRADAY_ACTIVATION_DELTA_PLAN_V1"
        and rebased_delta_plan.get("validation_status") == "PASS"
        and rebased_delta_plan.get("plan_status")
        == "READY_FOR_SEPARATE_ACTIVATION_IMPLEMENTATION_REVIEW",
        "FINAL_APPLY_REBASED_DELTA_PLAN_NOT_PASS",
    )
    require(rebased_delta_plan.get("main_sha") == current_main,
            "FINAL_APPLY_REBASED_DELTA_MAIN_MISMATCH")
    require(rebased_delta_plan.get("provider_name") == expected_provider_name,
            "FINAL_APPLY_REBASED_DELTA_PROVIDER_MISMATCH")
    require(rebased_delta_plan.get("license_basis") == expected_license_basis,
            "FINAL_APPLY_REBASED_DELTA_LICENSE_MISMATCH")
    require(
        rebased_delta_plan.get("provider_endpoint_template") == expected_endpoint_template,
        "FINAL_APPLY_REBASED_DELTA_ENDPOINT_MISMATCH",
    )
    credential = rebased_delta_plan.get("credential_boundary")
    require(
        isinstance(credential, Mapping)
        and credential.get("store") == "GITHUB_ACTIONS_SECRET"
        and credential.get("secret_name") == expected_secret_name
        and credential.get("secret_value_embedded") is False,
        "FINAL_APPLY_REBASED_DELTA_CREDENTIAL_MISMATCH",
    )
    require(
        set(rebased_delta_plan.get("existing_mutation_paths", []))
        == set(ALLOWED_EXISTING_MUTATION_PATHS)
        and set(rebased_delta_plan.get("new_runtime_files", []))
        == set(NEW_RUNTIME_FILES),
        "FINAL_APPLY_REBASED_DELTA_PATH_BOUNDARY_INVALID",
    )
    current_preimages = repo_preimage_hashes()
    require(
        rebased_delta_plan.get("existing_file_preimage_sha256") == current_preimages,
        "FINAL_APPLY_REBASED_DELTA_PREIMAGE_MISMATCH",
    )
    require(
        set(rebased_delta_plan.get("required_markets", [])) == REQUIRED_MARKETS
        and set(rebased_delta_plan.get("authorized_cadences", [])) == REQUIRED_CADENCES,
        "FINAL_APPLY_REBASED_DELTA_SCOPE_INVALID",
    )
    require(
        rebased_delta_plan.get("fallback_allowed") is False
        and rebased_delta_plan.get("automatic_retry_allowed") is False
        and rebased_delta_plan.get("apply_allowed") is False
        and rebased_delta_plan.get("activation_execution_allowed") is False
        and rebased_delta_plan.get("external_dependency_resolved") is False
        and rebased_delta_plan.get("registry_activation_allowed") is False
        and rebased_delta_plan.get("network_requests") == 0
        and rebased_delta_plan.get("credential_access") == 0
        and rebased_delta_plan.get("registry_mutations") == 0
        and rebased_delta_plan.get("scheduler_mutations") == 0
        and rebased_delta_plan.get("production_state_mutations") == 0
        and rebased_delta_plan.get("production_credit") == 0
        and rebased_delta_plan.get("cer081_credit") == 0,
        "FINAL_APPLY_REBASED_DELTA_PREMATURE_STATE",
    )

    # Full synthetic review must be rerun against the same current-main candidate.
    require(
        isinstance(rebased_synthetic_review, Mapping),
        "FINAL_APPLY_REBASED_SYNTHETIC_REVIEW_INVALID",
    )
    require(
        canonical_digest(rebased_synthetic_review) == synthetic_hash,
        "FINAL_APPLY_REBASED_SYNTHETIC_REVIEW_HASH_MISMATCH",
    )
    require(
        rebased_synthetic_review.get("artifact")
        == "RATE_INTRADAY_FULL_SYNTHETIC_ACTIVATION_CANDIDATE_REVIEW_V1"
        and rebased_synthetic_review.get("validation_status") == "PASS"
        and rebased_synthetic_review.get("review_disposition")
        == "READY_FOR_LIVE_EVIDENCE_BOUND_ACTIVATION_REVIEW",
        "FINAL_APPLY_REBASED_SYNTHETIC_REVIEW_NOT_PASS",
    )
    require(rebased_synthetic_review.get("main_sha") == current_main,
            "FINAL_APPLY_REBASED_SYNTHETIC_MAIN_MISMATCH")
    require(rebased_synthetic_review.get("provider_name") == expected_provider_name,
            "FINAL_APPLY_REBASED_SYNTHETIC_PROVIDER_MISMATCH")
    require(
        rebased_synthetic_review.get("candidate_manifest_sha256") == manifest_hash,
        "FINAL_APPLY_REBASED_CANDIDATE_MANIFEST_MISMATCH",
    )
    require(
        rebased_synthetic_review.get("coverage") == "30/30"
        and rebased_synthetic_review.get("market_counts") == {"TWSE": 25, "TPEX": 5}
        and rebased_synthetic_review.get("real_network_requests") == 0
        and rebased_synthetic_review.get("real_credential_access") == 0
        and rebased_synthetic_review.get("repository_writes") == 0
        and rebased_synthetic_review.get("provider_accepted") is False
        and rebased_synthetic_review.get("apply_allowed") is False
        and rebased_synthetic_review.get("activation_execution_allowed") is False
        and rebased_synthetic_review.get("external_dependency_resolved") is False
        and rebased_synthetic_review.get("registry_activation_allowed") is False
        and rebased_synthetic_review.get("production_credit") == 0
        and rebased_synthetic_review.get("cer081_credit") == 0,
        "FINAL_APPLY_REBASED_SYNTHETIC_BOUNDARY_INVALID",
    )

    live_cadences = live_binding.get("live_evidence_cadences")
    require(
        isinstance(live_cadences, list)
        and len(live_cadences) == 1
        and live_cadences[0] in REQUIRED_CADENCES,
        "FINAL_APPLY_LIVE_CADENCE_SCOPE_INVALID",
    )
    untested = sorted(REQUIRED_CADENCES - set(live_cadences))
    require(
        sorted(live_binding.get("live_untested_cadences", [])) == untested,
        "FINAL_APPLY_LIVE_UNTESTED_CADENCE_MISMATCH",
    )

    return {
        "artifact": "RATE_INTRADAY_FINAL_MAIN_ACTIVATION_APPLY_READINESS_V1",
        "validation_status": "PASS",
        "review_disposition": "READY_FOR_CONTROL_CENTER_ACTIVATION_APPLY_AUTHORIZATION",
        "current_main_sha": current_main,
        "historical_live_binding_sha256": live_hash,
        "historical_candidate_base_main_sha": live_binding.get("candidate_base_main_sha"),
        "rebased_delta_plan_sha256": delta_hash,
        "rebased_synthetic_review_sha256": synthetic_hash,
        "rebased_candidate_manifest_sha256": manifest_hash,
        "provider_name": expected_provider_name,
        "license_basis": expected_license_basis,
        "live_evidence_cadences": list(live_cadences),
        "live_untested_cadences": untested,
        "current_repo_preimage_sha256": current_preimages,
        "historical_evidence_rewritten": False,
        "provider_accepted": True,
        "apply_allowed": False,
        "activation_execution_allowed": False,
        "external_dependency_resolved": False,
        "registry_activation_allowed": False,
        "production_credit": 0,
        "cer081_credit": 0,
        "next_gate": "EXPLICIT_CONTROL_CENTER_ACTIVATION_APPLY_AUTHORIZATION",
    }

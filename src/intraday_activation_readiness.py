"""Pure offline readiness gate for future RATE intraday Production activation.

This module does not activate anything. It binds already-qualified admission
artifacts to the current repository preimage and to an exact future mutation
boundary. Live-provider qualification and a final Control Center activation
decision remain mandatory downstream gates.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
import re
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[1]
HEX40 = re.compile(r"^[0-9a-f]{40}$")
HEX64 = re.compile(r"^[0-9a-f]{64}$")
REQUIRED_MARKETS = {"TWSE", "TPEX"}
REQUIRED_CADENCES = {"09:30", "12:00"}
DEPENDENCY_ID = "EXTERNAL_AUTHORIZED_INTRADAY_FEED_DEPENDENCY"
DATASET_ID = "authorized_market_intraday"
ALLOWED_EXISTING_MUTATION_PATHS = (
    "config/RATE_EXTERNAL_PRODUCTION_DEPENDENCIES.json",
    "config/SOURCE_REGISTRY.json",
    "config/RATE_PRODUCTION_OFFICIAL_SOURCE_REGISTRY_V1.json",
    "src/phase2_production.py",
    "scripts/build_phase2_production_source.py",
    ".github/workflows/rate_production_0930_scheduler.yml",
    ".github/workflows/rate_production_1200_scheduler.yml",
)


class ActivationReadinessError(RuntimeError):
    pass


def require(condition: bool, reason: str) -> None:
    if not condition:
        raise ActivationReadinessError(reason)


def _hex40(value: Any, reason: str) -> str:
    text = str(value or "").lower()
    require(bool(HEX40.fullmatch(text)), reason)
    return text


def _hex64(value: Any, reason: str) -> str:
    text = str(value or "").lower()
    require(bool(HEX64.fullmatch(text)), reason)
    return text


def _sha256_file(relative: str) -> str:
    path = ROOT / relative
    require(path.is_file(), "INTRADAY_ACTIVATION_READINESS_PREIMAGE_FILE_MISSING:" + relative)
    return hashlib.sha256(path.read_bytes()).hexdigest()


def repo_preimage_hashes() -> dict[str, str]:
    return {relative: _sha256_file(relative) for relative in ALLOWED_EXISTING_MUTATION_PATHS}


def _exact_market_counts(value: Any, reason: str) -> dict[str, int]:
    require(isinstance(value, Mapping) and set(value) == REQUIRED_MARKETS, reason)
    require(all(isinstance(v, int) and not isinstance(v, bool) for v in value.values()), reason)
    normalized = {str(k).upper(): int(v) for k, v in value.items()}
    require(normalized == {"TWSE": 25, "TPEX": 5}, reason)
    return normalized


def validate_activation_readiness(
    package: Mapping[str, Any],
    *,
    expected_main_sha: str,
    expected_control_center_decision_id: str,
    expected_permit_sha256: str,
    expected_provider_authority_binding_sha256: str,
    expected_payload_qualification_sha256: str,
) -> dict[str, Any]:
    main_sha = _hex40(expected_main_sha, "INTRADAY_READINESS_EXPECTED_MAIN_SHA_INVALID")
    require(
        isinstance(expected_control_center_decision_id, str)
        and expected_control_center_decision_id.strip(),
        "INTRADAY_READINESS_EXPECTED_CONTROL_CENTER_DECISION_ID_MISSING",
    )
    permit_hash = _hex64(expected_permit_sha256, "INTRADAY_READINESS_EXPECTED_PERMIT_HASH_INVALID")
    provider_hash = _hex64(
        expected_provider_authority_binding_sha256,
        "INTRADAY_READINESS_EXPECTED_PROVIDER_AUTHORITY_HASH_INVALID",
    )
    payload_hash = _hex64(
        expected_payload_qualification_sha256,
        "INTRADAY_READINESS_EXPECTED_PAYLOAD_HASH_INVALID",
    )

    require(isinstance(package, Mapping), "INTRADAY_ACTIVATION_READINESS_PACKAGE_INVALID")
    require(
        package.get("artifact") == "RATE_INTRADAY_ACTIVATION_READINESS_PACKAGE_V1",
        "INTRADAY_ACTIVATION_READINESS_ARTIFACT_INVALID",
    )
    require(package.get("status") == "ENGINEERING_READINESS_ONLY",
            "INTRADAY_ACTIVATION_READINESS_STATUS_INVALID")
    require(package.get("activation_execution_status") == "NOT_AUTHORIZED",
            "INTRADAY_ACTIVATION_PREMATURE_EXECUTION_AUTHORITY")
    require(package.get("control_center_decision_id") == expected_control_center_decision_id,
            "INTRADAY_ACTIVATION_READINESS_DECISION_BINDING_MISMATCH")
    require(_hex40(package.get("main_sha"), "INTRADAY_ACTIVATION_READINESS_MAIN_SHA_INVALID") == main_sha,
            "INTRADAY_ACTIVATION_READINESS_MAIN_BINDING_MISMATCH")
    require(package.get("fallback_allowed") is False,
            "INTRADAY_ACTIVATION_READINESS_FALLBACK_FORBIDDEN")
    require(package.get("automatic_retry_allowed") is False,
            "INTRADAY_ACTIVATION_READINESS_AUTORETRY_FORBIDDEN")
    require(package.get("production_credit_before_activation") == 0,
            "INTRADAY_ACTIVATION_PREMATURE_PRODUCTION_CREDIT")
    require(package.get("cer081_credit_before_activation") == 0,
            "INTRADAY_ACTIVATION_PREMATURE_CER081_CREDIT")

    paths = package.get("allowed_existing_mutation_paths")
    require(
        isinstance(paths, list)
        and len(paths) == len(ALLOWED_EXISTING_MUTATION_PATHS)
        and set(paths) == set(ALLOWED_EXISTING_MUTATION_PATHS),
        "INTRADAY_ACTIVATION_MUTATION_BOUNDARY_INVALID",
    )
    preimages = package.get("preimage_sha256")
    trusted_preimages = repo_preimage_hashes()
    require(isinstance(preimages, Mapping) and set(preimages) == set(trusted_preimages),
            "INTRADAY_ACTIVATION_PREIMAGE_SET_INVALID")
    for relative, trusted in trusted_preimages.items():
        require(
            _hex64(preimages.get(relative), "INTRADAY_ACTIVATION_PREIMAGE_HASH_INVALID:" + relative) == trusted,
            "INTRADAY_ACTIVATION_PREIMAGE_HASH_MISMATCH:" + relative,
        )

    target = package.get("target")
    require(isinstance(target, Mapping), "INTRADAY_ACTIVATION_TARGET_MISSING")
    require(target.get("external_dependency_id") == DEPENDENCY_ID,
            "INTRADAY_ACTIVATION_TARGET_DEPENDENCY_MISMATCH")
    require(target.get("source_registry_dataset_id") == DATASET_ID,
            "INTRADAY_ACTIVATION_TARGET_DATASET_MISMATCH")
    require({str(v).upper() for v in target.get("required_markets", [])} == REQUIRED_MARKETS,
            "INTRADAY_ACTIVATION_TARGET_MARKETS_INVALID")
    require({str(v) for v in target.get("authorized_cadences", [])} == REQUIRED_CADENCES,
            "INTRADAY_ACTIVATION_TARGET_CADENCES_INVALID")
    require(target.get("fallback_allowed") is False and target.get("automatic_retry_allowed") is False,
            "INTRADAY_ACTIVATION_TARGET_FAIL_CLOSED_REQUIRED")

    permit = package.get("permit_qualification")
    require(isinstance(permit, Mapping), "INTRADAY_ACTIVATION_PERMIT_QUALIFICATION_MISSING")
    require(permit.get("artifact") == "RATE_INTRADAY_ACTIVATION_PERMIT_QUALIFICATION_V1"
            and permit.get("validation_status") == "PASS",
            "INTRADAY_ACTIVATION_PERMIT_QUALIFICATION_NOT_PASS")
    require(_hex64(permit.get("permit_sha256"), "INTRADAY_ACTIVATION_PERMIT_HASH_INVALID") == permit_hash,
            "INTRADAY_ACTIVATION_PERMIT_HASH_BINDING_MISMATCH")
    require(permit.get("control_center_decision_id") == expected_control_center_decision_id,
            "INTRADAY_ACTIVATION_PERMIT_DECISION_BINDING_MISMATCH")
    require(permit.get("main_sha") == main_sha,
            "INTRADAY_ACTIVATION_PERMIT_MAIN_BINDING_MISMATCH")
    require(set(permit.get("required_markets", [])) == REQUIRED_MARKETS,
            "INTRADAY_ACTIVATION_PERMIT_MARKETS_INVALID")
    require(set(permit.get("authorized_cadences", [])) == REQUIRED_CADENCES,
            "INTRADAY_ACTIVATION_PERMIT_CADENCES_INVALID")
    require(
        permit.get("network_requests") == 0
        and permit.get("credential_access") == 0
        and permit.get("registry_mutations") == 0
        and permit.get("scheduler_mutations") == 0
        and permit.get("production_state_mutations") == 0
        and permit.get("cer081_credit") == 0
        and permit.get("activation_execution_status") == "NOT_EXECUTED_BY_VALIDATOR",
        "INTRADAY_ACTIVATION_PERMIT_SIDE_EFFECT_BOUNDARY_INVALID",
    )

    provider = package.get("provider_authority_qualification")
    require(isinstance(provider, Mapping), "INTRADAY_PROVIDER_AUTHORITY_QUALIFICATION_MISSING")
    require(provider.get("artifact") == "RATE_INTRADAY_PROVIDER_AUTHORITY_QUALIFICATION_V1"
            and provider.get("validation_status") == "PASS",
            "INTRADAY_PROVIDER_AUTHORITY_QUALIFICATION_NOT_PASS")
    require(
        _hex64(provider.get("authority_binding_sha256"),
               "INTRADAY_PROVIDER_AUTHORITY_BINDING_HASH_INVALID") == provider_hash,
        "INTRADAY_PROVIDER_AUTHORITY_BINDING_HASH_MISMATCH",
    )
    require(set(provider.get("required_markets", [])) == REQUIRED_MARKETS
            and set(provider.get("market_coverage", [])) == REQUIRED_MARKETS,
            "INTRADAY_PROVIDER_AUTHORITY_MARKET_COVERAGE_INVALID")
    require(provider.get("automated_non_display_use") is True
            and provider.get("internal_use_only") is True
            and provider.get("fallback_allowed") is False,
            "INTRADAY_PROVIDER_AUTHORITY_USAGE_BOUNDARY_INVALID")
    require(provider.get("production_activation_allowed") is False
            and provider.get("network_requests") == 0
            and provider.get("credential_access") == 0
            and provider.get("registry_mutations") == 0,
            "INTRADAY_PROVIDER_AUTHORITY_SIDE_EFFECT_BOUNDARY_INVALID")

    payload = package.get("payload_qualification")
    require(isinstance(payload, Mapping), "INTRADAY_PAYLOAD_QUALIFICATION_MISSING")
    require(payload.get("artifact") == "RATE_AUTHORIZED_TAIWAN_INTRADAY_PAYLOAD_QUALIFICATION_V1"
            and payload.get("validation_status") == "PASS",
            "INTRADAY_PAYLOAD_QUALIFICATION_NOT_PASS")
    require(_hex64(payload.get("sha256"), "INTRADAY_PAYLOAD_QUALIFICATION_HASH_INVALID") == payload_hash,
            "INTRADAY_PAYLOAD_QUALIFICATION_HASH_MISMATCH")
    require(payload.get("expected_count") == 30 and payload.get("selected_count") == 30
            and payload.get("coverage") == "30/30",
            "INTRADAY_PAYLOAD_COVERAGE_INVALID")
    _exact_market_counts(payload.get("expected_market_counts"), "INTRADAY_PAYLOAD_MARKET_COUNTS_INVALID")
    _exact_market_counts(payload.get("selected_market_counts"), "INTRADAY_PAYLOAD_MARKET_COUNTS_INVALID")
    require(set(payload.get("licensed_markets", [])) == REQUIRED_MARKETS,
            "INTRADAY_PAYLOAD_LICENSE_MARKETS_INVALID")
    require(payload.get("fallback_used") is False
            and payload.get("network_requests") == 0
            and payload.get("credential_access") == 0
            and payload.get("production_eligible") is False
            and payload.get("registry_activated") is False,
            "INTRADAY_PAYLOAD_PREACTIVATION_BOUNDARY_INVALID")

    credential = package.get("credential_boundary")
    require(isinstance(credential, Mapping), "INTRADAY_ACTIVATION_CREDENTIAL_BOUNDARY_MISSING")
    require(credential.get("store") == "GITHUB_ACTIONS_SECRET",
            "INTRADAY_ACTIVATION_CREDENTIAL_STORE_INVALID")
    require(isinstance(credential.get("secret_name"), str) and credential["secret_name"].strip(),
            "INTRADAY_ACTIVATION_SECRET_NAME_MISSING")
    require(credential.get("secret_value_embedded") is False,
            "INTRADAY_ACTIVATION_SECRET_VALUE_FORBIDDEN")
    require(credential["secret_name"] == provider.get("credential_secret_name"),
            "INTRADAY_ACTIVATION_SECRET_NAME_BINDING_MISMATCH")

    runtime = package.get("provider_runtime")
    require(isinstance(runtime, Mapping), "INTRADAY_ACTIVATION_PROVIDER_RUNTIME_MISSING")
    require(runtime.get("provider_selected") is False
            and runtime.get("provider_name") is None
            and runtime.get("endpoint") is None,
            "INTRADAY_ACTIVATION_PROVIDER_SELECTION_PREMATURE")
    require(runtime.get("live_qualification_status") == "REQUIRED_NOT_YET_BOUND",
            "INTRADAY_ACTIVATION_LIVE_QUALIFICATION_PREMATURE")

    return {
        "artifact": "RATE_INTRADAY_ACTIVATION_READINESS_QUALIFICATION_V1",
        "validation_status": "PASS",
        "main_sha": main_sha,
        "control_center_decision_id": expected_control_center_decision_id,
        "permit_sha256": permit_hash,
        "provider_authority_binding_sha256": provider_hash,
        "payload_qualification_sha256": payload_hash,
        "preimage_sha256": trusted_preimages,
        "allowed_existing_mutation_paths": list(ALLOWED_EXISTING_MUTATION_PATHS),
        "external_dependency_id": DEPENDENCY_ID,
        "source_registry_dataset_id": DATASET_ID,
        "required_markets": sorted(REQUIRED_MARKETS),
        "authorized_cadences": sorted(REQUIRED_CADENCES),
        "network_requests": 0,
        "credential_access": 0,
        "registry_mutations": 0,
        "scheduler_mutations": 0,
        "production_state_mutations": 0,
        "production_credit": 0,
        "cer081_credit": 0,
        "activation_execution_allowed": False,
        "remaining_gates": [
            "LIVE_PROVIDER_QUALIFICATION",
            "INDEPENDENT_LIVE_REVIEW",
            "CONTROL_CENTER_FINAL_ACTIVATION_DECISION",
            "ACTIVATION_IMPLEMENTATION",
        ],
    }

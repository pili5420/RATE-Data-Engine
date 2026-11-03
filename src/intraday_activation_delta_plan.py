"""Pure dry-run builder for the future RATE intraday activation delta.

This module describes and validates the exact future activation mutation boundary.
It never writes repository files, never reads credentials, and never authorizes
activation execution.
"""
from __future__ import annotations

import re
from typing import Any, Mapping
from urllib.parse import urlparse

from .intraday_activation_readiness import (
    ALLOWED_EXISTING_MUTATION_PATHS,
    repo_preimage_hashes,
)

HEX40 = re.compile(r"^[0-9a-f]{40}$")
HEX64 = re.compile(r"^[0-9a-f]{64}$")
REQUIRED_MARKETS = ["TWSE", "TPEX"]
REQUIRED_CADENCES = ["09:30", "12:00"]
NEW_RUNTIME_FILES = (
    "src/intraday_provider_runtime.py",
    "scripts/acquire_intraday_provider_feed.py",
)


class ActivationDeltaPlanError(RuntimeError):
    pass


def require(condition: bool, reason: str) -> None:
    if not condition:
        raise ActivationDeltaPlanError(reason)


def _sha40(value: Any, reason: str) -> str:
    text = str(value or "").lower()
    require(bool(HEX40.fullmatch(text)), reason)
    return text


def _sha64(value: Any, reason: str) -> str:
    text = str(value or "").lower()
    require(bool(HEX64.fullmatch(text)), reason)
    return text


def _validate_endpoint(provider_name: str, endpoint_template: str) -> str:
    require(isinstance(endpoint_template, str) and endpoint_template.strip(),
            "ACTIVATION_DELTA_ENDPOINT_MISSING")
    parsed = urlparse(endpoint_template)
    require(parsed.scheme == "https" and parsed.hostname,
            "ACTIVATION_DELTA_ENDPOINT_NOT_HTTPS")
    require(not parsed.username and not parsed.password
            and not parsed.query and not parsed.fragment,
            "ACTIVATION_DELTA_ENDPOINT_UNSAFE_COMPONENT")
    require("{symbol}" in endpoint_template,
            "ACTIVATION_DELTA_ENDPOINT_SYMBOL_TEMPLATE_REQUIRED")
    if provider_name.lower() == "fugle":
        require(parsed.hostname.lower() == "api.fugle.tw",
                "ACTIVATION_DELTA_FUGLE_HOST_MISMATCH")
    return endpoint_template


def build_activation_delta_plan(
    readiness: Mapping[str, Any],
    provider_acceptance: Mapping[str, Any],
    *,
    expected_main_sha: str,
    control_center_activation_decision_id: str,
    provider_endpoint_template: str,
    credential_secret_name: str,
) -> dict[str, Any]:
    main_sha = _sha40(expected_main_sha, "ACTIVATION_DELTA_EXPECTED_MAIN_SHA_INVALID")
    require(
        isinstance(control_center_activation_decision_id, str)
        and control_center_activation_decision_id.strip(),
        "ACTIVATION_DELTA_DECISION_ID_MISSING",
    )
    require(
        isinstance(credential_secret_name, str) and credential_secret_name.strip(),
        "ACTIVATION_DELTA_SECRET_NAME_MISSING",
    )

    require(isinstance(readiness, Mapping), "ACTIVATION_DELTA_READINESS_INVALID")
    require(
        readiness.get("artifact") == "RATE_INTRADAY_ACTIVATION_READINESS_QUALIFICATION_V1"
        and readiness.get("validation_status") == "PASS",
        "ACTIVATION_DELTA_READINESS_NOT_PASS",
    )
    require(readiness.get("main_sha") == main_sha,
            "ACTIVATION_DELTA_READINESS_MAIN_MISMATCH")
    require(readiness.get("activation_execution_allowed") is False
            and readiness.get("production_credit") == 0
            and readiness.get("cer081_credit") == 0,
            "ACTIVATION_DELTA_READINESS_PREMATURE_STATE")
    require(
        set(readiness.get("allowed_existing_mutation_paths", []))
        == set(ALLOWED_EXISTING_MUTATION_PATHS),
        "ACTIVATION_DELTA_READINESS_MUTATION_BOUNDARY_MISMATCH",
    )

    trusted_preimages = repo_preimage_hashes()
    supplied_preimages = readiness.get("preimage_sha256")
    require(
        isinstance(supplied_preimages, Mapping)
        and set(supplied_preimages) == set(trusted_preimages),
        "ACTIVATION_DELTA_READINESS_PREIMAGE_SET_INVALID",
    )
    for path, trusted_hash in trusted_preimages.items():
        require(
            _sha64(
                supplied_preimages.get(path),
                "ACTIVATION_DELTA_READINESS_PREIMAGE_HASH_INVALID:" + path,
            ) == trusted_hash,
            "ACTIVATION_DELTA_READINESS_PREIMAGE_HASH_MISMATCH:" + path,
        )

    require(isinstance(provider_acceptance, Mapping),
            "ACTIVATION_DELTA_PROVIDER_ACCEPTANCE_INVALID")
    require(
        provider_acceptance.get("artifact") == "RATE_INTRADAY_PROVIDER_ACCEPTANCE_V1"
        and provider_acceptance.get("validation_status") == "PASS"
        and provider_acceptance.get("provider_accepted") is True,
        "ACTIVATION_DELTA_PROVIDER_NOT_ACCEPTED",
    )
    require(provider_acceptance.get("main_sha") == main_sha,
            "ACTIVATION_DELTA_PROVIDER_ACCEPTANCE_MAIN_MISMATCH")
    require(provider_acceptance.get("activation_execution_allowed") is False
            and provider_acceptance.get("external_dependency_resolved") is False
            and provider_acceptance.get("registry_activation_allowed") is False
            and provider_acceptance.get("production_credit") == 0
            and provider_acceptance.get("cer081_credit") == 0,
            "ACTIVATION_DELTA_PROVIDER_ACCEPTANCE_PREMATURE_STATE")
    require(
        set(provider_acceptance.get("required_markets", [])) == set(REQUIRED_MARKETS)
        and set(provider_acceptance.get("authorized_cadences", [])) == set(REQUIRED_CADENCES),
        "ACTIVATION_DELTA_PROVIDER_SCOPE_INVALID",
    )

    provider_name = provider_acceptance.get("provider_name")
    require(isinstance(provider_name, str) and provider_name.strip(),
            "ACTIVATION_DELTA_PROVIDER_NAME_MISSING")
    endpoint = _validate_endpoint(provider_name, provider_endpoint_template)

    mutation_specs = {
        "config/RATE_EXTERNAL_PRODUCTION_DEPENDENCIES.json": {
            "operation": "MODIFY_JSON",
            "required_postconditions": {
                "dependency_id": "EXTERNAL_AUTHORIZED_INTRADAY_FEED_DEPENDENCY",
                "status": "PASS",
                "engineering_resolution_available": True,
                "required_market_coverage": list(REQUIRED_MARKETS),
                "fallback_allowed": False,
                "cer081_completion_allowed_while_blocked": False,
            },
        },
        "config/SOURCE_REGISTRY.json": {
            "operation": "MODIFY_JSON",
            "required_postconditions": {
                "domain": "market_intraday",
                "provider": provider_name,
                "endpoint_or_path": endpoint,
                "authorization_status": "PASS",
                "operational_use_allowed": True,
                "intraday_status": {
                    "0930": "AUTHORIZED_PROVIDER_READY",
                    "1200": "AUTHORIZED_PROVIDER_READY",
                },
            },
        },
        "config/RATE_PRODUCTION_OFFICIAL_SOURCE_REGISTRY_V1.json": {
            "operation": "MODIFY_JSON",
            "required_postconditions": {
                "dataset_id": "authorized_market_intraday",
                "authority": provider_name,
                "endpoint": endpoint,
                "authorization_status": "PASS",
                "required_market_coverage": list(REQUIRED_MARKETS),
                "cadence_applicability": {
                    "07:30": "NOT_APPLICABLE",
                    "09:30": "REQUIRED",
                    "12:00": "REQUIRED",
                    "19:30": "NOT_APPLICABLE",
                },
                "fallback_allowed": False,
            },
        },
        "src/phase2_production.py": {
            "operation": "MODIFY_CODE",
            "required_postconditions": [
                "require_intraday_authority accepts only authoritative dependency PASS",
                "no unconditional PUBLIC_OFFICIAL_PARTIAL_RUNTIME_REQUIRED after PASS",
                "validate_phase2_source_bundle accepts all four RATE cadences and selects INTRADAY_REQUIRED_DATASETS for 09:30/12:00",
                "intraday_decision_gate_status returns PASS for 09:30/12:00 and NOT_APPLICABLE for 07:30/19:30",
                "decision_from_evaluation uses intraday_decision_gate_status for market_intraday_price_gate and full_intraday_decision_status",
                "validate_transition enforces the same cadence-derived intraday gate status",
                "09:30/12:00 still require Phase2 authoritative admission replay",
                "fallback remains forbidden",
            ],
        },
        "scripts/build_phase2_production_source.py": {
            "operation": "REVIEW_OR_MODIFY_CODE",
            "required_postconditions": [
                "authorized intraday feed is admitted before material binding",
                "feed and qualification digest binding remain mandatory",
                "provider network acquisition is not performed inside the Phase2 builder",
            ],
        },
        ".github/workflows/rate_production_0930_scheduler.yml": {
            "operation": "MODIFY_WORKFLOW",
            "required_postconditions": [
                "provider acquisition precedes Phase2 source build",
                "credential injected only from approved GitHub Actions secret",
                "no secret output",
                "no automatic retry or fallback provider",
                "Phase2 publish occurs only after all admission gates PASS",
            ],
        },
        ".github/workflows/rate_production_1200_scheduler.yml": {
            "operation": "MODIFY_WORKFLOW",
            "required_postconditions": [
                "provider acquisition precedes Phase2 source build",
                "credential injected only from approved GitHub Actions secret",
                "no secret output",
                "no automatic retry or fallback provider",
                "Phase2 publish occurs only after all admission gates PASS",
            ],
        },
    }
    require(set(mutation_specs) == set(ALLOWED_EXISTING_MUTATION_PATHS),
            "ACTIVATION_DELTA_INTERNAL_MUTATION_SPEC_MISMATCH")

    return {
        "artifact": "RATE_INTRADAY_ACTIVATION_DELTA_PLAN_V1",
        "validation_status": "PASS",
        "plan_status": "READY_FOR_SEPARATE_ACTIVATION_IMPLEMENTATION_REVIEW",
        "main_sha": main_sha,
        "control_center_activation_decision_id": control_center_activation_decision_id,
        "provider_name": provider_name,
        "license_basis": provider_acceptance.get("license_basis"),
        "provider_endpoint_template": endpoint,
        "credential_boundary": {
            "store": "GITHUB_ACTIONS_SECRET",
            "secret_name": credential_secret_name,
            "secret_value_embedded": False,
        },
        "existing_file_preimage_sha256": trusted_preimages,
        "existing_mutation_paths": list(ALLOWED_EXISTING_MUTATION_PATHS),
        "new_runtime_files": list(NEW_RUNTIME_FILES),
        "mutation_specs": mutation_specs,
        "required_markets": list(REQUIRED_MARKETS),
        "authorized_cadences": list(REQUIRED_CADENCES),
        "fallback_allowed": False,
        "automatic_retry_allowed": False,
        "apply_allowed": False,
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
    }

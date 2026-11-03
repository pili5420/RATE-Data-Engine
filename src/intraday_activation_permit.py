"""Offline validator for a future RATE intraday Production activation permit.

Validation is pure and has no side effects. A PASS does not mutate registry,
scheduler, Decision State, Portfolio, Ledger or Production pointers. A permit is
not self-authorizing: its decision identity and canonical permit hash must match
values independently supplied by the Control Center call site.
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
DEPENDENCY_ID = "EXTERNAL_AUTHORIZED_INTRADAY_FEED_DEPENDENCY"
DATASET_ID = "authorized_market_intraday"


class ActivationPermitError(RuntimeError):
    pass


def require(condition: bool, reason: str) -> None:
    if not condition:
        raise ActivationPermitError(reason)


def canonical_digest(value: Mapping[str, Any], *, omit: set[str] | None = None) -> str:
    omit = omit or set()
    body = {k: v for k, v in value.items() if k not in omit}
    return hashlib.sha256(json.dumps(body, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":")).encode("utf-8")).hexdigest()


def validate_activation_permit(
    permit: Mapping[str, Any],
    *,
    expected_main_sha: str,
    expected_universe_sha256: str,
    expected_provider_authority_sha256: str,
    expected_payload_contract_sha256: str,
    expected_control_center_decision_id: str,
    expected_permit_sha256: str,
) -> dict[str, Any]:
    require(
        isinstance(expected_control_center_decision_id, str)
        and expected_control_center_decision_id.strip(),
        "INTRADAY_EXPECTED_CONTROL_CENTER_DECISION_ID_MISSING",
    )
    expected_permit_hash = str(expected_permit_sha256 or "").lower()
    require(bool(HEX64.fullmatch(expected_permit_hash)),
            "INTRADAY_EXPECTED_PERMIT_HASH_INVALID")

    require(isinstance(permit, Mapping), "INTRADAY_ACTIVATION_PERMIT_INVALID")
    require(permit.get("artifact") == "RATE_INTRADAY_PRODUCTION_ACTIVATION_PERMIT_V1",
            "INTRADAY_ACTIVATION_ARTIFACT_INVALID")
    require(permit.get("status") == "INTRADAY_PRODUCTION_ACTIVATION_AUTHORIZED",
            "INTRADAY_ACTIVATION_NOT_AUTHORIZED")
    require(permit.get("control_center_decision") == "PASS",
            "INTRADAY_CONTROL_CENTER_DECISION_NOT_PASS")
    require(permit.get("control_center_decision_id") == expected_control_center_decision_id,
            "INTRADAY_CONTROL_CENTER_DECISION_BINDING_MISMATCH")
    require(permit.get("single_use") is True, "INTRADAY_ACTIVATION_SINGLE_USE_REQUIRED")
    require(permit.get("fallback_allowed") is False, "INTRADAY_ACTIVATION_FALLBACK_FORBIDDEN")
    require(permit.get("automatic_retry_allowed") is False,
            "INTRADAY_ACTIVATION_AUTORETRY_FORBIDDEN")
    require(permit.get("cer081_credit_before_activation") == 0,
            "INTRADAY_PREMATURE_CER081_CREDIT")

    main_sha = str(permit.get("main_sha") or "")
    require(bool(HEX40.fullmatch(main_sha)) and main_sha == expected_main_sha,
            "INTRADAY_ACTIVATION_MAIN_BINDING")

    require(permit.get("external_dependency_id") == DEPENDENCY_ID,
            "INTRADAY_ACTIVATION_DEPENDENCY_BINDING")
    require(permit.get("source_registry_dataset_id") == DATASET_ID,
            "INTRADAY_ACTIVATION_REGISTRY_BINDING")

    markets = {str(v).upper() for v in permit.get("required_markets", [])}
    cadences = {str(v) for v in permit.get("authorized_cadences", [])}
    require(markets == REQUIRED_MARKETS, "INTRADAY_ACTIVATION_DUAL_MARKET_REQUIRED")
    require(cadences == REQUIRED_CADENCES, "INTRADAY_ACTIVATION_CADENCE_SCOPE_INVALID")

    universe = permit.get("production_universe")
    require(isinstance(universe, Mapping), "INTRADAY_ACTIVATION_UNIVERSE_BINDING_MISSING")
    require(universe.get("count") == 30, "INTRADAY_ACTIVATION_UNIVERSE_COUNT_INVALID")
    universe_hash = str(universe.get("sha256") or "").lower()
    require(bool(HEX64.fullmatch(universe_hash)) and universe_hash == expected_universe_sha256,
            "INTRADAY_ACTIVATION_UNIVERSE_HASH_MISMATCH")
    market_counts = universe.get("market_counts")
    require(isinstance(market_counts, Mapping)
            and set(market_counts) == REQUIRED_MARKETS
            and all(isinstance(v, int) and not isinstance(v, bool) for v in market_counts.values())
            and sum(market_counts.values()) == 30
            and all(v > 0 for v in market_counts.values()),
            "INTRADAY_ACTIVATION_UNIVERSE_MARKET_COVERAGE_INVALID")

    provider = permit.get("provider_authority")
    require(isinstance(provider, Mapping), "INTRADAY_ACTIVATION_PROVIDER_AUTHORITY_MISSING")
    require(provider.get("validation_status") == "PASS",
            "INTRADAY_ACTIVATION_PROVIDER_AUTHORITY_NOT_PASS")
    provider_hash = str(provider.get("sha256") or "").lower()
    require(bool(HEX64.fullmatch(provider_hash))
            and provider_hash == expected_provider_authority_sha256,
            "INTRADAY_ACTIVATION_PROVIDER_AUTHORITY_HASH_MISMATCH")
    require(set(str(v).upper() for v in provider.get("markets", [])) == REQUIRED_MARKETS,
            "INTRADAY_ACTIVATION_PROVIDER_MARKET_COVERAGE_INVALID")
    require(provider.get("automated_non_display_use") is True,
            "INTRADAY_ACTIVATION_NON_DISPLAY_AUTHORITY_REQUIRED")

    payload = permit.get("payload_contract")
    require(isinstance(payload, Mapping), "INTRADAY_ACTIVATION_PAYLOAD_CONTRACT_MISSING")
    payload_hash = str(payload.get("sha256") or "").lower()
    require(payload.get("validation_status") == "PASS"
            and bool(HEX64.fullmatch(payload_hash))
            and payload_hash == expected_payload_contract_sha256,
            "INTRADAY_ACTIVATION_PAYLOAD_CONTRACT_BINDING")
    require(payload.get("explicit_timezone_required") is True
            and payload.get("exact_symbol_market_binding") is True
            and payload.get("freshness_fail_closed") is True,
            "INTRADAY_ACTIVATION_PAYLOAD_GATES_INCOMPLETE")

    require(permit.get("credential_value_embedded") is False,
            "INTRADAY_ACTIVATION_SECRET_EMBEDDED")
    require(isinstance(permit.get("credential_secret_name"), str)
            and permit["credential_secret_name"].strip(),
            "INTRADAY_ACTIVATION_SECRET_REFERENCE_MISSING")

    identity = str(permit.get("permit_sha256") or "").lower()
    require(bool(HEX64.fullmatch(identity)), "INTRADAY_ACTIVATION_PERMIT_HASH_INVALID")
    require(identity == canonical_digest(permit, omit={"permit_sha256"}),
            "INTRADAY_ACTIVATION_PERMIT_HASH_MISMATCH")
    require(identity == expected_permit_hash,
            "INTRADAY_ACTIVATION_EXPECTED_PERMIT_HASH_MISMATCH")

    return {
        "artifact": "RATE_INTRADAY_ACTIVATION_PERMIT_QUALIFICATION_V1",
        "validation_status": "PASS",
        "control_center_decision_id": expected_control_center_decision_id,
        "permit_sha256": identity,
        "main_sha": main_sha,
        "required_markets": sorted(REQUIRED_MARKETS),
        "authorized_cadences": sorted(REQUIRED_CADENCES),
        "universe_count": 30,
        "external_dependency_id": DEPENDENCY_ID,
        "source_registry_dataset_id": DATASET_ID,
        "fallback_allowed": False,
        "automatic_retry_allowed": False,
        "network_requests": 0,
        "credential_access": 0,
        "registry_mutations": 0,
        "scheduler_mutations": 0,
        "production_state_mutations": 0,
        "cer081_credit": 0,
        "activation_execution_status": "NOT_EXECUTED_BY_VALIDATOR",
    }

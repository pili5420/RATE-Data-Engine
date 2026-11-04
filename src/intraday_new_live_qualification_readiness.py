"""Pure readiness gate for a fresh single-live RATE intraday qualification.

This module composes provider-written confirmation and already-qualified exchange
authority. It does not issue a Control Center permit and performs no network I/O.
"""
from __future__ import annotations

import re
from typing import Any, Mapping

HEX40 = re.compile(r"^[0-9a-f]{40}$")
HEX64 = re.compile(r"^[0-9a-f]{64}$")
REQUIRED_MARKETS = {"TWSE", "TPEX"}


class NewLiveQualificationReadinessError(RuntimeError):
    pass


def require(condition: bool, reason: str) -> None:
    if not condition:
        raise NewLiveQualificationReadinessError(reason)


def _hex40(value: Any, reason: str) -> str:
    text = str(value or "").lower()
    require(bool(HEX40.fullmatch(text)), reason)
    return text


def _hex64(value: Any, reason: str) -> str:
    text = str(value or "").lower()
    require(bool(HEX64.fullmatch(text)), reason)
    return text


def validate_new_live_qualification_readiness(
    *,
    main_sha: str,
    provider_confirmation: Mapping[str, Any],
    exchange_intake: Mapping[str, Any],
    provider_authority: Mapping[str, Any],
) -> dict[str, Any]:
    main = _hex40(main_sha, "NEW_LIVE_READINESS_MAIN_SHA_INVALID")

    require(isinstance(provider_confirmation, Mapping),
            "NEW_LIVE_READINESS_PROVIDER_CONFIRMATION_INVALID")
    require(provider_confirmation.get("provider") == "Fugle",
            "NEW_LIVE_READINESS_PROVIDER_MISMATCH")
    require(provider_confirmation.get("provider_license_basis") == "PROVIDER_WRITTEN_CONFIRMED",
            "NEW_LIVE_READINESS_PROVIDER_WRITTEN_CONFIRMATION_REQUIRED")
    scope = provider_confirmation.get("provider_confirmed_scope")
    require(isinstance(scope, Mapping), "NEW_LIVE_READINESS_PROVIDER_SCOPE_MISSING")
    require(
        scope.get("personal_internal_only") is True
        and scope.get("single_user_only") is True
        and scope.get("automated_non_display_analysis") is True
        and scope.get("approximately_30_requests_per_cadence_allowed") is True,
        "NEW_LIVE_READINESS_PROVIDER_SCOPE_INVALID",
    )
    require(provider_confirmation.get("previous_single_use_live_permit_reusable") is False,
            "NEW_LIVE_READINESS_PREVIOUS_PERMIT_MUST_NOT_BE_REUSED")
    require(provider_confirmation.get("new_live_qualification_requires_fresh_control_center_authorization") is True,
            "NEW_LIVE_READINESS_FRESH_AUTHORIZATION_FLAG_REQUIRED")

    require(isinstance(exchange_intake, Mapping),
            "NEW_LIVE_READINESS_EXCHANGE_INTAKE_INVALID")
    require(exchange_intake.get("artifact") == "RATE_INTRADAY_EXCHANGE_AUTHORITY_EVIDENCE_INTAKE_V1",
            "NEW_LIVE_READINESS_EXCHANGE_INTAKE_ARTIFACT_INVALID")
    require(exchange_intake.get("validation_status") == "PASS",
            "NEW_LIVE_READINESS_EXCHANGE_INTAKE_NOT_PASS")
    require(set(exchange_intake.get("exchange_evidence", {})) == REQUIRED_MARKETS,
            "NEW_LIVE_READINESS_EXCHANGE_COVERAGE_INVALID")
    require(exchange_intake.get("private_evidence_bytes_read") == 0,
            "NEW_LIVE_READINESS_PRIVATE_EVIDENCE_BOUNDARY_INVALID")
    expected_binding_hash = _hex64(
        exchange_intake.get("expected_binding_sha256"),
        "NEW_LIVE_READINESS_EXPECTED_BINDING_HASH_INVALID",
    )

    require(isinstance(provider_authority, Mapping),
            "NEW_LIVE_READINESS_PROVIDER_AUTHORITY_INVALID")
    require(provider_authority.get("artifact") == "RATE_INTRADAY_PROVIDER_AUTHORITY_QUALIFICATION_V1",
            "NEW_LIVE_READINESS_PROVIDER_AUTHORITY_ARTIFACT_INVALID")
    require(provider_authority.get("validation_status") == "PASS",
            "NEW_LIVE_READINESS_PROVIDER_AUTHORITY_NOT_PASS")
    require(provider_authority.get("provider_name") == "Fugle",
            "NEW_LIVE_READINESS_PROVIDER_AUTHORITY_PROVIDER_MISMATCH")
    require(set(provider_authority.get("market_coverage", [])) == REQUIRED_MARKETS,
            "NEW_LIVE_READINESS_PROVIDER_AUTHORITY_COVERAGE_INVALID")
    require(provider_authority.get("automated_non_display_use") is True
            and provider_authority.get("internal_use_only") is True,
            "NEW_LIVE_READINESS_PROVIDER_AUTHORITY_SCOPE_INVALID")
    require(provider_authority.get("fallback_allowed") is False,
            "NEW_LIVE_READINESS_FALLBACK_FORBIDDEN")
    require(provider_authority.get("production_activation_allowed") is False,
            "NEW_LIVE_READINESS_PREMATURE_PRODUCTION_AUTHORITY")
    require(_hex64(
        provider_authority.get("authority_binding_sha256"),
        "NEW_LIVE_READINESS_AUTHORITY_BINDING_HASH_INVALID",
    ) == expected_binding_hash,
            "NEW_LIVE_READINESS_AUTHORITY_BINDING_MISMATCH")

    return {
        "artifact": "RATE_INTRADAY_NEW_SINGLE_LIVE_QUALIFICATION_READINESS_V1",
        "validation_status": "PASS",
        "readiness_disposition": "READY_FOR_CONTROL_CENTER_NEW_SINGLE_LIVE_AUTHORIZATION",
        "main_sha": main,
        "provider_name": "Fugle",
        "markets": ["TPEX", "TWSE"],
        "authorized_candidate_cadences": ["09:30", "12:00"],
        "provider_written_confirmation": True,
        "exchange_authority_qualified": True,
        "provider_authority_qualified": True,
        "fresh_control_center_authorization_required": True,
        "previous_single_use_permit_reusable": False,
        "live_requests_authorized_by_this_gate": 0,
        "network_requests": 0,
        "credential_access": 0,
        "registry_mutations": 0,
        "scheduler_mutations": 0,
        "production_activation_allowed": False,
        "external_dependency_resolved": False,
        "production_credit": 0,
        "cer081_credit": 0,
        "next_gate": "CONTROL_CENTER_NEW_SINGLE_LIVE_QUALIFICATION_AUTHORIZATION",
    }

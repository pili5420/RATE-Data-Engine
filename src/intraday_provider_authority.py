"""Offline qualification for RATE authorized Taiwan intraday provider authority.

This module validates a provider authority manifest only when it is bound to an
independent Control-Center-supplied expected authority binding. It performs no
network I/O, reads no credentials, selects no provider, and cannot activate the
Production source registry.
"""
from __future__ import annotations

from datetime import date
import hashlib
import json
import re
from typing import Any, Mapping

REQUIRED_MARKETS = {"TWSE", "TPEX"}
HEX64 = re.compile(r"^[0-9a-f]{64}$")
ALLOWED_CREDENTIAL_STORES = {"GITHUB_ACTIONS_SECRET", "EXTERNAL_SECRET_MANAGER"}
ALLOWED_TRANSPORTS = {"HTTPS", "WSS", "TCP_TLS", "VENDOR_SDK_TLS"}


class ProviderAuthorityError(RuntimeError):
    pass


def require(condition: bool, reason: str) -> None:
    if not condition:
        raise ProviderAuthorityError(reason)


def _iso_day(value: Any, reason: str) -> date:
    require(isinstance(value, str) and value, reason)
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise ProviderAuthorityError(reason) from exc
    require(parsed.isoformat() == value, reason)
    return parsed


def _hex64(value: Any, reason: str) -> str:
    digest = str(value or "").lower()
    require(bool(HEX64.fullmatch(digest)), reason)
    return digest


def _binding_digest(value: Mapping[str, Any]) -> str:
    body = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(body).hexdigest()


def _expected_binding(value: Mapping[str, Any]) -> dict[str, Any]:
    require(isinstance(value, Mapping), "PROVIDER_EXPECTED_BINDING_INVALID")
    require(value.get("artifact") == "RATE_INTRADAY_PROVIDER_AUTHORITY_EXPECTED_BINDING_V1",
            "PROVIDER_EXPECTED_BINDING_ARTIFACT_INVALID")
    decision_id = value.get("control_center_decision_id")
    require(isinstance(decision_id, str) and decision_id.strip(),
            "PROVIDER_EXPECTED_CONTROL_CENTER_DECISION_ID_MISSING")
    provider_name = value.get("provider_name")
    service_id = value.get("service_id")
    secret_name = value.get("credential_secret_name")
    require(isinstance(provider_name, str) and provider_name.strip(),
            "PROVIDER_EXPECTED_NAME_MISSING")
    require(isinstance(service_id, str) and service_id.strip(),
            "PROVIDER_EXPECTED_SERVICE_ID_MISSING")
    require(isinstance(secret_name, str) and secret_name.strip(),
            "PROVIDER_EXPECTED_SECRET_NAME_MISSING")

    valid_from = _iso_day(value.get("valid_from"), "PROVIDER_EXPECTED_VALID_FROM_INVALID")
    valid_through = _iso_day(value.get("valid_through"), "PROVIDER_EXPECTED_VALID_THROUGH_INVALID")
    require(valid_from <= valid_through, "PROVIDER_EXPECTED_VALIDITY_WINDOW_INVALID")

    evidence = value.get("exchange_evidence")
    require(isinstance(evidence, Mapping), "PROVIDER_EXPECTED_EXCHANGE_EVIDENCE_MISSING")
    require(set(evidence) == REQUIRED_MARKETS, "PROVIDER_EXPECTED_EXCHANGE_EVIDENCE_SET_INVALID")
    normalized_evidence: dict[str, dict[str, str]] = {}
    for market in sorted(REQUIRED_MARKETS):
        item = evidence[market]
        require(isinstance(item, Mapping), f"PROVIDER_EXPECTED_{market}_EVIDENCE_INVALID")
        reference = item.get("evidence_reference")
        require(isinstance(reference, str) and reference.strip(),
                f"PROVIDER_EXPECTED_{market}_EVIDENCE_REFERENCE_MISSING")
        normalized_evidence[market] = {
            "evidence_reference": reference,
            "evidence_sha256": _hex64(
                item.get("evidence_sha256"),
                f"PROVIDER_EXPECTED_{market}_EVIDENCE_HASH_INVALID",
            ),
        }

    return {
        "artifact": value["artifact"],
        "control_center_decision_id": decision_id,
        "provider_name": provider_name,
        "service_id": service_id,
        "credential_secret_name": secret_name,
        "valid_from": valid_from.isoformat(),
        "valid_through": valid_through.isoformat(),
        "exchange_evidence": normalized_evidence,
    }


def _evidence(value: Any, market: str, expected: Mapping[str, str]) -> None:
    require(isinstance(value, Mapping), f"PROVIDER_{market}_AUTHORITY_MISSING")
    require(value.get("contract_status") == "ACTIVE", f"PROVIDER_{market}_CONTRACT_NOT_ACTIVE")
    require(value.get("real_time_trading_information") is True,
            f"PROVIDER_{market}_REALTIME_RIGHT_MISSING")
    require(value.get("automated_non_display_use") is True,
            f"PROVIDER_{market}_NON_DISPLAY_RIGHT_MISSING")
    require(value.get("internal_analysis_use") is True,
            f"PROVIDER_{market}_INTERNAL_ANALYSIS_RIGHT_MISSING")
    require(value.get("redistribution_allowed") is False,
            f"PROVIDER_{market}_REDISTRIBUTION_BOUNDARY_INVALID")
    require(isinstance(value.get("contract_id"), str) and value["contract_id"].strip(),
            f"PROVIDER_{market}_CONTRACT_ID_MISSING")
    reference = value.get("evidence_reference")
    require(isinstance(reference, str) and reference.strip(),
            f"PROVIDER_{market}_EVIDENCE_REFERENCE_MISSING")
    digest = _hex64(value.get("evidence_sha256"), f"PROVIDER_{market}_EVIDENCE_HASH_INVALID")
    require(reference == expected["evidence_reference"],
            f"PROVIDER_{market}_EVIDENCE_REFERENCE_MISMATCH")
    require(digest == expected["evidence_sha256"],
            f"PROVIDER_{market}_EVIDENCE_HASH_MISMATCH")


def qualify_provider_authority(
    manifest: Mapping[str, Any],
    *,
    trading_date: str,
    expected_binding: Mapping[str, Any],
) -> dict[str, Any]:
    expected = _expected_binding(expected_binding)

    require(isinstance(manifest, Mapping), "PROVIDER_AUTHORITY_MANIFEST_INVALID")
    require(manifest.get("artifact") == "RATE_AUTHORIZED_TAIWAN_INTRADAY_PROVIDER_AUTHORITY_V1",
            "PROVIDER_AUTHORITY_ARTIFACT_INVALID")
    require(manifest.get("control_center_approval_status") == "PASS",
            "PROVIDER_CONTROL_CENTER_APPROVAL_NOT_PASS")
    require(manifest.get("control_center_decision_id") == expected["control_center_decision_id"],
            "PROVIDER_CONTROL_CENTER_DECISION_BINDING_MISMATCH")
    require(manifest.get("fallback_allowed") is False, "PROVIDER_FALLBACK_FORBIDDEN")
    require(manifest.get("production_activation_status") == "NOT_AUTHORIZED",
            "PROVIDER_PREMATURE_PRODUCTION_ACTIVATION")

    provider = manifest.get("provider")
    require(isinstance(provider, Mapping), "PROVIDER_IDENTITY_MISSING")
    require(isinstance(provider.get("name"), str) and provider["name"].strip(),
            "PROVIDER_NAME_MISSING")
    require(isinstance(provider.get("service_id"), str) and provider["service_id"].strip(),
            "PROVIDER_SERVICE_ID_MISSING")
    require(provider["name"] == expected["provider_name"], "PROVIDER_NAME_BINDING_MISMATCH")
    require(provider["service_id"] == expected["service_id"], "PROVIDER_SERVICE_ID_BINDING_MISMATCH")

    service = manifest.get("service_contract")
    require(isinstance(service, Mapping), "PROVIDER_SERVICE_CONTRACT_MISSING")
    markets = {str(v).upper() for v in service.get("markets", [])}
    require(markets == REQUIRED_MARKETS, "PROVIDER_DUAL_MARKET_COVERAGE_REQUIRED")
    require(service.get("data_class") == "REAL_TIME_TRADING_INFORMATION",
            "PROVIDER_DATA_CLASS_INVALID")
    require(service.get("non_display_automated_analysis") is True,
            "PROVIDER_NON_DISPLAY_USE_NOT_AUTHORIZED")
    require(service.get("internal_use_only") is True,
            "PROVIDER_INTERNAL_USE_BOUNDARY_REQUIRED")
    require(str(service.get("transport") or "").upper() in ALLOWED_TRANSPORTS,
            "PROVIDER_TRANSPORT_NOT_QUALIFIED")
    require(service.get("timestamp_timezone_explicit") is True,
            "PROVIDER_TIMESTAMP_TIMEZONE_CONTRACT_REQUIRED")

    credential = manifest.get("credential_boundary")
    require(isinstance(credential, Mapping), "PROVIDER_CREDENTIAL_BOUNDARY_MISSING")
    require(credential.get("secret_value_embedded") is False,
            "PROVIDER_SECRET_VALUE_EMBEDDED")
    require(credential.get("repository_secret_material") is False,
            "PROVIDER_REPOSITORY_SECRET_FORBIDDEN")
    require(credential.get("store") in ALLOWED_CREDENTIAL_STORES,
            "PROVIDER_CREDENTIAL_STORE_INVALID")
    require(isinstance(credential.get("secret_name"), str) and credential["secret_name"].strip(),
            "PROVIDER_SECRET_NAME_MISSING")
    require(credential["secret_name"] == expected["credential_secret_name"],
            "PROVIDER_SECRET_NAME_BINDING_MISMATCH")

    authorities = manifest.get("exchange_authorizations")
    require(isinstance(authorities, Mapping), "PROVIDER_EXCHANGE_AUTHORIZATIONS_MISSING")
    require(set(authorities) == REQUIRED_MARKETS, "PROVIDER_EXCHANGE_AUTHORITY_SET_INVALID")
    for market in sorted(REQUIRED_MARKETS):
        _evidence(authorities[market], market, expected["exchange_evidence"][market])

    valid_from = _iso_day(manifest.get("valid_from"), "PROVIDER_VALID_FROM_INVALID")
    valid_through = _iso_day(manifest.get("valid_through"), "PROVIDER_VALID_THROUGH_INVALID")
    require(valid_from.isoformat() == expected["valid_from"], "PROVIDER_VALID_FROM_BINDING_MISMATCH")
    require(valid_through.isoformat() == expected["valid_through"], "PROVIDER_VALID_THROUGH_BINDING_MISMATCH")
    target = _iso_day(trading_date, "PROVIDER_TRADING_DATE_INVALID")
    require(valid_from <= target <= valid_through, "PROVIDER_AUTHORITY_OUTSIDE_VALIDITY_WINDOW")

    return {
        "artifact": "RATE_INTRADAY_PROVIDER_AUTHORITY_QUALIFICATION_V1",
        "validation_status": "PASS",
        "control_center_decision_id": expected["control_center_decision_id"],
        "authority_binding_sha256": _binding_digest(expected),
        "provider_name": provider["name"],
        "service_id": provider["service_id"],
        "required_markets": sorted(REQUIRED_MARKETS),
        "market_coverage": sorted(markets),
        "trading_date": trading_date,
        "valid_from": valid_from.isoformat(),
        "valid_through": valid_through.isoformat(),
        "automated_non_display_use": True,
        "internal_use_only": True,
        "fallback_allowed": False,
        "credential_store": credential["store"],
        "credential_secret_name": credential["secret_name"],
        "credential_access": 0,
        "network_requests": 0,
        "provider_selected_by_module": False,
        "registry_mutations": 0,
        "production_activation_allowed": False,
        "production_admission_status": "SEPARATE_PROVIDER_RUNTIME_AND_CONTROL_CENTER_ACTIVATION_REQUIRED",
    }

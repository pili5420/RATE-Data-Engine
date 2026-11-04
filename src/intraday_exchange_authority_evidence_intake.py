"""Build a metadata-only exchange-authority intake package for RATE V11.

This module never reads private evidence bytes and never grants Production authority.
It validates externally supplied evidence references/digests and emits the exact
Control-Center expected binding shape consumed by intraday_provider_authority.py.
"""
from __future__ import annotations

from datetime import date
import hashlib
import json
import re
from typing import Any, Mapping

HEX64 = re.compile(r"^[0-9a-f]{64}$")
REQUIRED_MARKETS = ("TWSE", "TPEX")


class ExchangeAuthorityEvidenceIntakeError(RuntimeError):
    pass


def require(condition: bool, reason: str) -> None:
    if not condition:
        raise ExchangeAuthorityEvidenceIntakeError(reason)


def _day(value: Any, reason: str) -> str:
    require(isinstance(value, str) and value, reason)
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise ExchangeAuthorityEvidenceIntakeError(reason) from exc
    require(parsed.isoformat() == value, reason)
    return value


def _digest(value: Any, reason: str) -> str:
    text = str(value or "").lower()
    require(bool(HEX64.fullmatch(text)), reason)
    return text


def _canonical_digest(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def build_exchange_authority_intake(
    *,
    control_center_decision_id: str,
    provider_name: str,
    service_id: str,
    credential_secret_name: str,
    valid_from: str,
    valid_through: str,
    exchange_evidence: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    require(isinstance(control_center_decision_id, str) and control_center_decision_id.strip(),
            "EXCHANGE_INTAKE_DECISION_ID_MISSING")
    require(isinstance(provider_name, str) and provider_name.strip(),
            "EXCHANGE_INTAKE_PROVIDER_NAME_MISSING")
    require(isinstance(service_id, str) and service_id.strip(),
            "EXCHANGE_INTAKE_SERVICE_ID_MISSING")
    require(isinstance(credential_secret_name, str) and credential_secret_name.strip(),
            "EXCHANGE_INTAKE_SECRET_NAME_MISSING")

    start = _day(valid_from, "EXCHANGE_INTAKE_VALID_FROM_INVALID")
    end = _day(valid_through, "EXCHANGE_INTAKE_VALID_THROUGH_INVALID")
    require(start <= end, "EXCHANGE_INTAKE_VALIDITY_WINDOW_INVALID")

    require(isinstance(exchange_evidence, Mapping),
            "EXCHANGE_INTAKE_EVIDENCE_INVALID")
    require(set(exchange_evidence) == set(REQUIRED_MARKETS),
            "EXCHANGE_INTAKE_EVIDENCE_SET_INVALID")

    normalized: dict[str, dict[str, Any]] = {}
    for market in REQUIRED_MARKETS:
        item = exchange_evidence[market]
        require(isinstance(item, Mapping), f"EXCHANGE_INTAKE_{market}_EVIDENCE_INVALID")
        reference = item.get("evidence_reference")
        require(isinstance(reference, str) and reference.strip(),
                f"EXCHANGE_INTAKE_{market}_REFERENCE_MISSING")
        digest = _digest(item.get("evidence_sha256"),
                         f"EXCHANGE_INTAKE_{market}_HASH_INVALID")
        require(item.get("private_evidence_content_embedded") is False,
                f"EXCHANGE_INTAKE_{market}_PRIVATE_CONTENT_FORBIDDEN")
        require(item.get("real_time_trading_information") is True,
                f"EXCHANGE_INTAKE_{market}_REALTIME_SCOPE_UNPROVEN")
        require(item.get("automated_non_display_use") is True,
                f"EXCHANGE_INTAKE_{market}_NON_DISPLAY_SCOPE_UNPROVEN")
        require(item.get("internal_analysis_use") is True,
                f"EXCHANGE_INTAKE_{market}_INTERNAL_ANALYSIS_SCOPE_UNPROVEN")
        require(item.get("contract_status") == "ACTIVE",
                f"EXCHANGE_INTAKE_{market}_CONTRACT_NOT_ACTIVE")
        contract_id = item.get("contract_id")
        require(isinstance(contract_id, str) and contract_id.strip(),
                f"EXCHANGE_INTAKE_{market}_CONTRACT_ID_MISSING")

        normalized[market] = {
            "evidence_reference": reference,
            "evidence_sha256": digest,
            "contract_status": "ACTIVE",
            "contract_id": contract_id,
            "real_time_trading_information": True,
            "automated_non_display_use": True,
            "internal_analysis_use": True,
            "redistribution_allowed": False,
            "private_evidence_content_embedded": False,
        }

    expected_binding = {
        "artifact": "RATE_INTRADAY_PROVIDER_AUTHORITY_EXPECTED_BINDING_V1",
        "control_center_decision_id": control_center_decision_id,
        "provider_name": provider_name,
        "service_id": service_id,
        "credential_secret_name": credential_secret_name,
        "valid_from": start,
        "valid_through": end,
        "exchange_evidence": {
            market: {
                "evidence_reference": normalized[market]["evidence_reference"],
                "evidence_sha256": normalized[market]["evidence_sha256"],
            }
            for market in REQUIRED_MARKETS
        },
    }

    package = {
        "artifact": "RATE_INTRADAY_EXCHANGE_AUTHORITY_EVIDENCE_INTAKE_V1",
        "validation_status": "PASS",
        "control_center_decision_id": control_center_decision_id,
        "provider_name": provider_name,
        "service_id": service_id,
        "valid_from": start,
        "valid_through": end,
        "exchange_evidence": normalized,
        "expected_binding": expected_binding,
        "expected_binding_sha256": _canonical_digest(expected_binding),
        "private_evidence_bytes_read": 0,
        "network_requests": 0,
        "credential_access": 0,
        "registry_mutations": 0,
        "scheduler_mutations": 0,
        "production_mutations": 0,
        "production_activation_allowed": False,
        "external_dependency_resolved": False,
        "cer081_credit": 0,
        "next_gate": "RATE_INTRADAY_PROVIDER_AUTHORITY_QUALIFICATION_V1",
    }
    return package

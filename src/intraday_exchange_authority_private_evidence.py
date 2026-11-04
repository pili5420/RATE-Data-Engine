"""Local-only helper for hashing private TWSE/TPEx authority evidence.

This module does not decide whether evidence is sufficient. It emits a metadata-only
manifest with status PENDING_CONTROL_CENTER_REVIEW. Private bytes are never returned.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

REQUIRED_SCOPE="ACTIVE_REALTIME_AUTOMATED_NONDISPLAY_INTERNAL"


class PrivateAuthorityEvidenceError(RuntimeError):
    pass


def require(condition: bool, reason: str) -> None:
    if not condition:
        raise PrivateAuthorityEvidenceError(reason)


def hash_private_evidence(
    path: str | Path,
    *,
    market: str,
    evidence_reference: str,
    contract_id: str,
    asserted_scope: str,
) -> dict[str, Any]:
    market=market.upper()
    require(market in {"TWSE","TPEX"},"PRIVATE_AUTH_MARKET_INVALID")
    require(isinstance(evidence_reference,str) and evidence_reference.strip(),
            "PRIVATE_AUTH_REFERENCE_MISSING")
    require(isinstance(contract_id,str) and contract_id.strip(),
            "PRIVATE_AUTH_CONTRACT_ID_MISSING")
    require(asserted_scope==REQUIRED_SCOPE,
            "PRIVATE_AUTH_SCOPE_ASSERTION_REQUIRED")

    file_path=Path(path)
    require(file_path.is_file(),"PRIVATE_AUTH_FILE_NOT_FOUND")
    require(not file_path.is_symlink(),"PRIVATE_AUTH_SYMLINK_FORBIDDEN")

    digest=hashlib.sha256()
    total=0
    try:
        with file_path.open("rb") as stream:
            while True:
                chunk=stream.read(1024*1024)
                if not chunk:
                    break
                digest.update(chunk)
                total += len(chunk)
    except OSError as exc:
        raise PrivateAuthorityEvidenceError("PRIVATE_AUTH_FILE_READ_FAILED") from exc

    require(total>0,"PRIVATE_AUTH_FILE_EMPTY")
    return {
        "market":market,
        "evidence_reference":evidence_reference,
        "evidence_sha256":digest.hexdigest(),
        "evidence_size_bytes":total,
        "contract_id":contract_id,
        "asserted_scope":asserted_scope,
        "private_evidence_content_embedded":False,
        "private_source_path_embedded":False,
        "control_center_review_status":"PENDING",
    }


def build_private_authority_manifest(
    twse: dict[str,Any],
    tpex: dict[str,Any],
    *,
    provider_name: str,
    service_id: str,
    credential_secret_name: str,
    valid_from: str,
    valid_through: str,
) -> dict[str,Any]:
    require(twse.get("market")=="TWSE" and tpex.get("market")=="TPEX",
            "PRIVATE_AUTH_DUAL_MARKET_INPUT_INVALID")
    require(isinstance(provider_name,str) and provider_name.strip(),
            "PRIVATE_AUTH_PROVIDER_MISSING")
    require(isinstance(service_id,str) and service_id.strip(),
            "PRIVATE_AUTH_SERVICE_ID_MISSING")
    require(isinstance(credential_secret_name,str) and credential_secret_name.strip(),
            "PRIVATE_AUTH_SECRET_NAME_MISSING")
    require(isinstance(valid_from,str) and valid_from
            and isinstance(valid_through,str) and valid_through,
            "PRIVATE_AUTH_VALIDITY_MISSING")

    return {
        "artifact":"RATE_INTRADAY_EXCHANGE_AUTHORITY_PRIVATE_EVIDENCE_MANIFEST_V1",
        "status":"PENDING_CONTROL_CENTER_REVIEW",
        "provider_name":provider_name,
        "service_id":service_id,
        "credential_secret_name":credential_secret_name,
        "valid_from":valid_from,
        "valid_through":valid_through,
        "exchange_evidence":{"TWSE":twse,"TPEX":tpex},
        "private_evidence_bytes_embedded":0,
        "private_source_paths_embedded":False,
        "authority_granted_by_manifest":False,
        "provider_authority_qualification_pass":False,
        "production_activation_allowed":False,
        "external_dependency_resolved":False,
        "production_credit":0,
        "cer081_credit":0,
        "next_gate":"CONTROL_CENTER_PRIVATE_EVIDENCE_REVIEW_THEN_EXCHANGE_AUTHORITY_INTAKE"
    }

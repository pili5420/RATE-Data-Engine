"""Offline R2 private-custody manifest preparation and integrity verification.

The caller supplies an independently pinned private-store attestation. This module
does not provision the store, inspect its ACLs, persist evidence, or upload data.
Only hashes and execution identities appear in the returned review manifest.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
import hashlib
import json
import re
from typing import Any

from .intraday_fugle_live_consumption_fence import canonical_digest


class FugleR2EvidenceError(RuntimeError):
    pass


def require(condition: bool, reason: str) -> None:
    if not condition:
        raise FugleR2EvidenceError(reason)


def _binding(value: Mapping[str, Any]) -> dict[str, Any]:
    require(isinstance(value, Mapping) and set(value) == {
        "source_sha", "workflow_sha256", "permit_id", "trigger_id",
        "run_id", "job_id", "run_attempt",
    }, "R2_EVIDENCE_BINDING_INVALID")
    for key, length in (("source_sha", 40), ("workflow_sha256", 64)):
        require(isinstance(value[key], str)
                and re.fullmatch(r"[0-9a-f]{" + str(length) + r"}", value[key]) is not None,
                "R2_EVIDENCE_SOURCE_BINDING_INVALID")
    for key in ("permit_id", "trigger_id"):
        require(isinstance(value[key], str)
                and re.fullmatch(r"[A-Za-z0-9_-]{1,128}", value[key]) is not None,
                "R2_EVIDENCE_EXECUTION_ID_INVALID")
    for key in ("run_id", "job_id", "run_attempt"):
        require(type(value[key]) is int and value[key] > 0,
                "R2_EVIDENCE_RUN_BINDING_INVALID")
    require(value["run_attempt"] == 1, "R2_EVIDENCE_REENTRY_FORBIDDEN")
    return dict(value)


def _private_custody(custody: Mapping[str, Any], expected_sha256: str) -> None:
    require(isinstance(expected_sha256, str)
            and re.fullmatch(r"[0-9a-f]{64}", expected_sha256) is not None,
            "R2_EVIDENCE_CUSTODY_PIN_INVALID")
    require(isinstance(custody, Mapping) and canonical_digest(custody) == expected_sha256,
            "R2_EVIDENCE_CUSTODY_PIN_MISMATCH")
    require(set(custody) == {
        "artifact", "custody_id", "control_center_decision_id", "visibility",
        "access_control_verified", "public_upload_allowed", "credential_persistence_allowed",
    }, "R2_EVIDENCE_CUSTODY_CONTRACT_INVALID")
    require(custody["artifact"] == "RATE_FUGLE_R2_PRIVATE_CUSTODY_ATTESTATION_V1"
            and custody["visibility"] == "PRIVATE"
            and custody["access_control_verified"] is True
            and custody["public_upload_allowed"] is False
            and custody["credential_persistence_allowed"] is False,
            "R2_EVIDENCE_PRIVATE_CUSTODY_UNPROVEN")
    for key in ("custody_id", "control_center_decision_id"):
        require(isinstance(custody[key], str)
                and re.fullmatch(r"[A-Za-z0-9_-]{1,128}", custody[key]) is not None,
                "R2_EVIDENCE_CUSTODY_REFERENCE_INVALID")


def _check_sanitized(value: Any) -> None:
    if isinstance(value, dict):
        forbidden = {
            "apikey", "fugleapikey", "githubtoken", "accesstoken", "token",
            "authorization", "cookie", "password", "secret", "raw", "rawresponse",
            "responsebody", "headers", "credential", "credentials",
        }
        require(not any(re.sub(r"[^a-z0-9]", "", key.casefold()) in forbidden for key in value),
                "R2_EVIDENCE_CREDENTIAL_OR_RAW_PAYLOAD_FORBIDDEN")
        for item in value.values():
            _check_sanitized(item)
    elif isinstance(value, list):
        for item in value:
            _check_sanitized(item)
    elif isinstance(value, str):
        require(not re.search(r"(?i)(?:bearer\s+|(?:api[_-]?key|token|password)=)", value),
                "R2_EVIDENCE_CREDENTIAL_OR_RAW_PAYLOAD_FORBIDDEN")


def build_r2_evidence_manifest(
    artifacts: Mapping[str, bytes],
    *,
    expected_artifacts: Sequence[str],
    binding: Mapping[str, Any],
    custody: Mapping[str, Any],
    expected_custody_sha256: str,
    status: str,
) -> dict[str, Any]:
    """Hash sanitized private evidence without returning any artifact contents.

    PARTIAL and UNKNOWN retain the full expected inventory and missing filenames.
    They always remain ineligible for independent review admission.
    """
    execution = _binding(binding)
    _private_custody(custody, expected_custody_sha256)
    require(status in {"COMPLETE", "PARTIAL", "UNKNOWN"}, "R2_EVIDENCE_STATUS_INVALID")
    require(isinstance(expected_artifacts, (list, tuple)) and bool(expected_artifacts),
            "R2_EVIDENCE_INVENTORY_REQUIRED")
    require(all(isinstance(name, str) and re.fullmatch(r"[A-Za-z0-9_-]+\.json", name)
                for name in expected_artifacts)
            and len(set(expected_artifacts)) == len(expected_artifacts),
            "R2_EVIDENCE_INVENTORY_INVALID")
    require(isinstance(artifacts, Mapping) and set(artifacts) <= set(expected_artifacts),
            "R2_EVIDENCE_UNEXPECTED_ARTIFACT")
    missing = sorted(set(expected_artifacts) - set(artifacts))
    require(status != "COMPLETE" or not missing, "R2_EVIDENCE_INCOMPLETE")
    entries = []
    for name in sorted(artifacts):
        payload = artifacts[name]
        require(type(payload) is bytes and bool(payload), "R2_EVIDENCE_PAYLOAD_INVALID")
        try:
            decoded = json.loads(payload)
        except (UnicodeError, ValueError):
            raise FugleR2EvidenceError("R2_EVIDENCE_JSON_INVALID") from None
        require(isinstance(decoded, dict), "R2_EVIDENCE_JSON_OBJECT_REQUIRED")
        _check_sanitized(decoded)
        entries.append({"name": name, "bytes": len(payload),
                        "sha256": hashlib.sha256(payload).hexdigest()})
    manifest = {
        "artifact": "RATE_FUGLE_R2_PRIVATE_EVIDENCE_MANIFEST_V1",
        "binding": execution,
        "custody_id": custody["custody_id"],
        "custody_attestation_sha256": expected_custody_sha256,
        "status": status,
        "expected_artifacts": sorted(expected_artifacts),
        "artifacts": entries,
        "missing_artifacts": missing,
        "review_eligible": status == "COMPLETE" and not missing,
        "artifact_contents_embedded": False,
        "public_upload_allowed": False,
        "credential_persistence_allowed": False,
        "production_credit": 0,
        "cer081_credit": 0,
    }
    return {**manifest, "manifest_sha256": canonical_digest(manifest)}


def verify_r2_evidence_manifest(
    manifest: Mapping[str, Any],
    artifacts: Mapping[str, bytes],
    *,
    expected_binding: Mapping[str, Any],
    expected_artifacts: Sequence[str],
    custody: Mapping[str, Any],
    expected_custody_sha256: str,
    expected_manifest_sha256: str,
) -> dict[str, Any]:
    require(isinstance(manifest, Mapping), "R2_EVIDENCE_MANIFEST_INVALID")
    require(isinstance(expected_manifest_sha256, str)
            and re.fullmatch(r"[0-9a-f]{64}", expected_manifest_sha256) is not None,
            "R2_EVIDENCE_MANIFEST_PIN_INVALID")
    require(manifest.get("manifest_sha256") == expected_manifest_sha256,
            "R2_EVIDENCE_MANIFEST_PIN_MISMATCH")
    rebuilt = build_r2_evidence_manifest(
        artifacts,
        expected_artifacts=expected_artifacts,
        binding=expected_binding,
        custody=custody,
        expected_custody_sha256=expected_custody_sha256,
        status=manifest.get("status"),
    )
    require(manifest == rebuilt, "R2_EVIDENCE_INTEGRITY_OR_BINDING_MISMATCH")
    require(rebuilt["review_eligible"], "R2_EVIDENCE_PARTIAL_OR_UNKNOWN")
    return rebuilt

"""Deterministic non-mutating transaction plan for a future RATE intraday activation apply.

The plan binds one qualified single-use authorization to one exact candidate and
one exact current repository preimage. It never creates blobs, commits, branches,
pull requests, or repository writes.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
import re
from typing import Any, Mapping

from .intraday_activation_apply_authorization import EXPECTED_PATHS
from .intraday_activation_candidate_materialization import candidate_manifest_sha256
from .intraday_activation_candidate_review import canonical_digest
from .intraday_activation_delta_plan import NEW_RUNTIME_FILES
from .intraday_activation_readiness import (
    ALLOWED_EXISTING_MUTATION_PATHS,
    ROOT,
    repo_preimage_hashes,
)

HEX40 = re.compile(r"^[0-9a-f]{40}$")
HEX64 = re.compile(r"^[0-9a-f]{64}$")
DECISION_ID = re.compile(r"^[A-Za-z0-9._-]{1,96}$")


class ActivationApplyTransactionPlanError(RuntimeError):
    pass


def require(condition: bool, reason: str) -> None:
    if not condition:
        raise ActivationApplyTransactionPlanError(reason)


def _sha40(value: Any, reason: str) -> str:
    text = str(value or "").lower()
    require(bool(HEX40.fullmatch(text)), reason)
    return text


def _sha64(value: Any, reason: str) -> str:
    text = str(value or "").lower()
    require(bool(HEX64.fullmatch(text)), reason)
    return text


def _git_blob_sha1(content: bytes) -> str:
    header = f"blob {len(content)}\0".encode("ascii")
    return hashlib.sha1(header + content).hexdigest()


def _current_new_file_absence() -> dict[str, bool]:
    return {
        path: not (ROOT / path).exists()
        for path in NEW_RUNTIME_FILES
    }


def build_activation_apply_transaction_plan(
    authorization_qualification: Mapping[str, Any],
    candidate_files: Mapping[str, str],
    *,
    expected_authorization_qualification_sha256: str,
    expected_current_main_sha: str,
    expected_candidate_manifest_sha256: str,
    expected_control_center_decision_id: str,
    expected_provider_name: str,
) -> dict[str, Any]:
    qualification_hash = _sha64(
        expected_authorization_qualification_sha256,
        "APPLY_PLAN_EXPECTED_AUTHORIZATION_QUALIFICATION_HASH_INVALID",
    )
    current_main = _sha40(
        expected_current_main_sha,
        "APPLY_PLAN_EXPECTED_CURRENT_MAIN_INVALID",
    )
    manifest_hash = _sha64(
        expected_candidate_manifest_sha256,
        "APPLY_PLAN_EXPECTED_CANDIDATE_MANIFEST_HASH_INVALID",
    )
    require(
        isinstance(expected_control_center_decision_id, str)
        and bool(DECISION_ID.fullmatch(expected_control_center_decision_id))
        and ".." not in expected_control_center_decision_id
        and not expected_control_center_decision_id.endswith(".")
        and not expected_control_center_decision_id.lower().endswith(".lock"),
        "APPLY_PLAN_EXPECTED_DECISION_ID_INVALID",
    )
    require(
        isinstance(expected_provider_name, str) and expected_provider_name.strip(),
        "APPLY_PLAN_EXPECTED_PROVIDER_INVALID",
    )

    require(
        isinstance(authorization_qualification, Mapping),
        "APPLY_PLAN_AUTHORIZATION_QUALIFICATION_INVALID",
    )
    require(
        canonical_digest(authorization_qualification) == qualification_hash,
        "APPLY_PLAN_AUTHORIZATION_QUALIFICATION_HASH_MISMATCH",
    )
    require(
        authorization_qualification.get("artifact")
        == "RATE_INTRADAY_ACTIVATION_APPLY_AUTHORIZATION_QUALIFICATION_V1"
        and authorization_qualification.get("validation_status") == "PASS"
        and authorization_qualification.get("authorization_valid") is True,
        "APPLY_PLAN_AUTHORIZATION_QUALIFICATION_NOT_PASS",
    )
    require(
        authorization_qualification.get("control_center_decision_id")
        == expected_control_center_decision_id,
        "APPLY_PLAN_DECISION_ID_MISMATCH",
    )
    require(
        authorization_qualification.get("current_main_sha") == current_main,
        "APPLY_PLAN_CURRENT_MAIN_MISMATCH",
    )
    require(
        authorization_qualification.get("candidate_manifest_sha256") == manifest_hash,
        "APPLY_PLAN_CANDIDATE_MANIFEST_BINDING_MISMATCH",
    )
    require(
        authorization_qualification.get("provider_name") == expected_provider_name,
        "APPLY_PLAN_PROVIDER_MISMATCH",
    )
    require(
        authorization_qualification.get("single_use") is True
        and authorization_qualification.get("automatic_retry_allowed") is False
        and authorization_qualification.get("fallback_allowed") is False
        and authorization_qualification.get("apply_executed") is False
        and authorization_qualification.get("activation_execution_allowed_by_this_validator") is False
        and authorization_qualification.get("external_dependency_resolved") is False
        and authorization_qualification.get("registry_activation_allowed") is False
        and authorization_qualification.get("repository_writes") == 0
        and authorization_qualification.get("live_provider_requests") == 0
        and authorization_qualification.get("production_credit") == 0
        and authorization_qualification.get("cer081_credit") == 0,
        "APPLY_PLAN_AUTHORIZATION_BOUNDARY_INVALID",
    )
    require(
        set(authorization_qualification.get("allowed_paths", [])) == set(EXPECTED_PATHS),
        "APPLY_PLAN_AUTHORIZATION_PATHS_INVALID",
    )

    require(
        isinstance(candidate_files, Mapping)
        and set(candidate_files) == set(EXPECTED_PATHS)
        and all(isinstance(v, str) and v for v in candidate_files.values()),
        "APPLY_PLAN_CANDIDATE_FILE_SET_INVALID",
    )
    require(
        candidate_manifest_sha256(candidate_files) == manifest_hash,
        "APPLY_PLAN_CANDIDATE_MANIFEST_HASH_MISMATCH",
    )

    base_preimages = repo_preimage_hashes()
    require(
        set(base_preimages) == set(ALLOWED_EXISTING_MUTATION_PATHS),
        "APPLY_PLAN_BASE_PREIMAGE_SET_INVALID",
    )
    new_file_absence = _current_new_file_absence()
    require(
        set(new_file_absence) == set(NEW_RUNTIME_FILES)
        and all(new_file_absence.values()),
        "APPLY_PLAN_NEW_RUNTIME_FILE_ALREADY_EXISTS",
    )

    files = {}
    for path in EXPECTED_PATHS:
        content = candidate_files[path].encode("utf-8")
        files[path] = {
            "mode": "100644",
            "content_sha256": hashlib.sha256(content).hexdigest(),
            "git_blob_sha1": _git_blob_sha1(content),
            "operation": (
                "REPLACE_EXISTING"
                if path in ALLOWED_EXISTING_MUTATION_PATHS
                else "CREATE_NEW"
            ),
            "base_sha256": base_preimages.get(path),
        }

    branch_name = (
        "activation/rate-v11-intraday-"
        + expected_control_center_decision_id.lower()
    )
    require(
        len(branch_name) <= 180
        and ".." not in branch_name
        and not branch_name.endswith(".")
        and not branch_name.lower().endswith(".lock"),
        "APPLY_PLAN_BRANCH_NAME_INVALID",
    )

    plan_core = {
        "artifact": "RATE_INTRADAY_ACTIVATION_APPLY_TRANSACTION_PLAN_V1",
        "status": "TRANSACTION_PLAN_ONLY",
        "control_center_decision_id": expected_control_center_decision_id,
        "authorization_qualification_sha256": qualification_hash,
        "base_main_sha": current_main,
        "candidate_manifest_sha256": manifest_hash,
        "provider_name": expected_provider_name,
        "single_use": True,
        "automatic_retry_allowed": False,
        "fallback_allowed": False,
        "target_branch": branch_name,
        "target_base": "main",
        "merge_allowed_by_plan": False,
        "direct_main_update_allowed": False,
        "files": files,
        "existing_file_preimage_sha256": base_preimages,
        "new_runtime_file_absence": new_file_absence,
        "apply_executed": False,
        "repository_writes": 0,
        "live_provider_requests": 0,
        "external_dependency_resolved": False,
        "registry_activation_allowed": False,
        "production_credit": 0,
        "cer081_credit": 0,
    }
    return {
        **plan_core,
        "transaction_plan_sha256": canonical_digest(plan_core),
        "next_gate": "SEPARATE_SINGLE_USE_GIT_TRANSACTION_EXECUTOR",
    }

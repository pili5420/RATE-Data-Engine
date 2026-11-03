"""Isolated materialization and readback review for the RATE intraday activation candidate.

This module may write only into an explicitly supplied empty workspace outside the
repository. It never applies candidate files to the repository and never performs a
real provider request.
"""
from __future__ import annotations

from datetime import datetime
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from .intraday_activation_candidate_review import (
    canonical_digest,
    validate_activation_candidate,
)
from .intraday_activation_candidate_runtime_review import (
    review_candidate_runtime_synthetic,
)
from .intraday_activation_candidate_syntax_review import (
    validate_activation_candidate_syntax,
)
from .intraday_activation_delta_plan import (
    NEW_RUNTIME_FILES,
)
from .intraday_activation_readiness import (
    ALLOWED_EXISTING_MUTATION_PATHS,
)

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_PATHS = tuple(sorted(
    set(ALLOWED_EXISTING_MUTATION_PATHS) | set(NEW_RUNTIME_FILES)
))


class CandidateMaterializationError(RuntimeError):
    pass


def require(condition: bool, reason: str) -> None:
    if not condition:
        raise CandidateMaterializationError(reason)


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def candidate_hashes(candidate_files: Mapping[str, str]) -> dict[str, str]:
    require(
        isinstance(candidate_files, Mapping)
        and set(candidate_files) == set(EXPECTED_PATHS),
        "ACTIVATION_MATERIALIZATION_FILE_SET_INVALID",
    )
    require(
        all(isinstance(value, str) and value for value in candidate_files.values()),
        "ACTIVATION_MATERIALIZATION_FILE_CONTENT_INVALID",
    )
    return {
        path: _sha256_text(candidate_files[path])
        for path in EXPECTED_PATHS
    }


def candidate_manifest_sha256(candidate_files: Mapping[str, str]) -> str:
    return canonical_digest({
        "artifact": "RATE_INTRADAY_ACTIVATION_CANDIDATE_FILE_MANIFEST_V1",
        "files": candidate_hashes(candidate_files),
    })


def _workspace(path: Path) -> Path:
    raw = Path(path)
    require(raw.exists() and raw.is_dir(), "ACTIVATION_MATERIALIZATION_WORKSPACE_INVALID")
    require(not raw.is_symlink(), "ACTIVATION_MATERIALIZATION_WORKSPACE_SYMLINK_FORBIDDEN")
    resolved = raw.resolve()
    repo = ROOT.resolve()
    require(resolved != repo and repo not in resolved.parents,
            "ACTIVATION_MATERIALIZATION_REPOSITORY_WRITE_FORBIDDEN")
    require(not any(raw.iterdir()), "ACTIVATION_MATERIALIZATION_WORKSPACE_NOT_EMPTY")
    return resolved


def _safe_relative(relative: str) -> Path:
    path = Path(relative)
    require(
        not path.is_absolute()
        and relative
        and relative == path.as_posix()
        and ".." not in path.parts
        and "." not in path.parts,
        "ACTIVATION_MATERIALIZATION_PATH_INVALID",
    )
    return path


def materialize_candidate_workspace(
    candidate_files: Mapping[str, str],
    *,
    workspace_root: Path,
    expected_candidate_manifest_sha256: str,
) -> dict[str, Any]:
    hashes = candidate_hashes(candidate_files)
    actual_manifest = candidate_manifest_sha256(candidate_files)
    require(
        actual_manifest == expected_candidate_manifest_sha256,
        "ACTIVATION_MATERIALIZATION_EXTERNAL_MANIFEST_HASH_MISMATCH",
    )
    root = _workspace(Path(workspace_root))

    written = []
    for relative in EXPECTED_PATHS:
        rel = _safe_relative(relative)
        target = root / rel
        resolved_parent = target.parent.resolve()
        require(root == resolved_parent or root in resolved_parent.parents,
                "ACTIVATION_MATERIALIZATION_PATH_ESCAPE")
        target.parent.mkdir(parents=True, exist_ok=True)
        require(not target.exists() and not target.is_symlink(),
                "ACTIVATION_MATERIALIZATION_EXCLUSIVE_CREATE_REQUIRED")
        with target.open("x", encoding="utf-8", newline="") as handle:
            handle.write(candidate_files[relative])
        require(
            target.read_bytes() == candidate_files[relative].encode("utf-8"),
            "ACTIVATION_MATERIALIZATION_READBACK_BYTES_MISMATCH",
        )
        require(
            hashlib.sha256(target.read_bytes()).hexdigest() == hashes[relative],
            "ACTIVATION_MATERIALIZATION_READBACK_HASH_MISMATCH",
        )
        written.append(relative)

    return {
        "artifact": "RATE_INTRADAY_ACTIVATION_CANDIDATE_MATERIALIZATION_V1",
        "validation_status": "PASS",
        "workspace_scope": "EXTERNAL_ISOLATED_WORKSPACE_ONLY",
        "candidate_manifest_sha256": actual_manifest,
        "materialized_paths": written,
        "materialized_file_sha256": hashes,
        "repository_writes": 0,
        "provider_requests": 0,
        "credential_access": 0,
        "apply_allowed": False,
        "activation_execution_allowed": False,
        "external_dependency_resolved": False,
        "registry_activation_allowed": False,
        "production_credit": 0,
        "cer081_credit": 0,
    }


def _load_workspace(root: Path) -> dict[str, str]:
    require(root.exists() and root.is_dir(), "ACTIVATION_MATERIALIZATION_WORKSPACE_INVALID")
    actual_files = {
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file()
    }
    require(actual_files == set(EXPECTED_PATHS),
            "ACTIVATION_MATERIALIZATION_READBACK_FILE_SET_INVALID")
    return {
        relative: (root / relative).read_text(encoding="utf-8")
        for relative in EXPECTED_PATHS
    }


def review_materialized_candidate_workspace(
    delta_plan: Mapping[str, Any],
    *,
    workspace_root: Path,
    expected_candidate_manifest_sha256: str,
    expected_delta_plan_sha256: str,
    expected_main_sha: str,
    expected_provider_name: str,
    expected_endpoint_template: str,
    expected_secret_name: str,
    expected_runtime_sha256: str,
    trading_date: str,
    cadence: str,
    now_utc: datetime,
) -> dict[str, Any]:
    root = Path(workspace_root).resolve()
    repo = ROOT.resolve()
    require(root != repo and repo not in root.parents,
            "ACTIVATION_MATERIALIZATION_REPOSITORY_WRITE_FORBIDDEN")
    candidate_files = _load_workspace(root)
    require(
        candidate_manifest_sha256(candidate_files) == expected_candidate_manifest_sha256,
        "ACTIVATION_MATERIALIZATION_READBACK_MANIFEST_HASH_MISMATCH",
    )

    static_review = validate_activation_candidate(
        delta_plan,
        candidate_files,
        expected_delta_plan_sha256=expected_delta_plan_sha256,
        expected_main_sha=expected_main_sha,
        expected_provider_name=expected_provider_name,
        expected_endpoint_template=expected_endpoint_template,
        expected_secret_name=expected_secret_name,
    )
    syntax_review = validate_activation_candidate_syntax(
        candidate_files,
        expected_provider_name=expected_provider_name,
        expected_secret_name=expected_secret_name,
    )
    runtime_review = review_candidate_runtime_synthetic(
        candidate_files,
        expected_runtime_sha256=expected_runtime_sha256,
        expected_provider_name=expected_provider_name,
        expected_secret_name=expected_secret_name,
        trading_date=trading_date,
        cadence=cadence,
        now_utc=now_utc,
    )
    require(
        static_review.get("validation_status") == "PASS"
        and syntax_review.get("validation_status") == "PASS"
        and runtime_review.get("validation_status") == "PASS",
        "ACTIVATION_MATERIALIZATION_DOWNSTREAM_REVIEW_NOT_PASS",
    )
    return {
        "artifact": "RATE_INTRADAY_ACTIVATION_CANDIDATE_MATERIALIZED_REVIEW_V1",
        "validation_status": "PASS",
        "candidate_manifest_sha256": expected_candidate_manifest_sha256,
        "static_review": static_review,
        "syntax_review": syntax_review,
        "runtime_semantic_review": runtime_review,
        "real_network_requests": 0,
        "repository_writes": 0,
        "credential_access": 0,
        "apply_allowed": False,
        "activation_execution_allowed": False,
        "external_dependency_resolved": False,
        "registry_activation_allowed": False,
        "production_credit": 0,
        "cer081_credit": 0,
    }

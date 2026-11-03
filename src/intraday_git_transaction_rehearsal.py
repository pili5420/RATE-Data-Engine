"""Synthetic single-use Git transaction executor rehearsal for RATE intraday activation.

This module can execute only against SyntheticGitBackend. It models Git object/ref
mutation semantics without contacting GitHub or changing any real repository.
"""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Mapping

from .intraday_activation_candidate_materialization import candidate_manifest_sha256
from .intraday_activation_candidate_review import canonical_digest
from .intraday_activation_apply_authorization import EXPECTED_PATHS

HEX40 = re.compile(r"^[0-9a-f]{40}$")
HEX64 = re.compile(r"^[0-9a-f]{64}$")


class GitTransactionRehearsalError(RuntimeError):
    pass


def require(condition: bool, reason: str) -> None:
    if not condition:
        raise GitTransactionRehearsalError(reason)


def _sha40(value: Any, reason: str) -> str:
    text = str(value or "").lower()
    require(bool(HEX40.fullmatch(text)), reason)
    return text


def _sha64(value: Any, reason: str) -> str:
    text = str(value or "").lower()
    require(bool(HEX64.fullmatch(text)), reason)
    return text


def _git_blob_sha1(content: bytes) -> str:
    return hashlib.sha1(
        f"blob {len(content)}\0".encode("ascii") + content
    ).hexdigest()


def _synthetic_sha1(kind: str, value: Mapping[str, Any]) -> str:
    payload = json.dumps(
        value, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    body = kind.encode("ascii") + b"\0" + payload
    return hashlib.sha1(body).hexdigest()


class SyntheticGitBackend:
    """In-memory Git-like backend. Never contacts a real repository."""

    transport = "SYNTHETIC_IN_MEMORY_ONLY"

    def __init__(
        self,
        *,
        main_sha: str,
        main_tree_sha: str = "a" * 40,
        fail_at: str | None = None,
    ):
        self.refs = {"main": main_sha}
        self.main_tree_sha = main_tree_sha
        self.fail_at = fail_at
        self.calls: list[str] = []
        self.blobs: dict[str, bytes] = {}
        self.trees: dict[str, dict[str, Any]] = {}
        self.commits: dict[str, dict[str, Any]] = {}
        self.consumed_tokens: set[str] = set()

    def _fail(self, point: str) -> None:
        if self.fail_at == point:
            raise RuntimeError("SYNTHETIC_GIT_FAIL:" + point)

    def consume(self, token: str) -> None:
        self.calls.append("consume:" + token)
        require(token not in self.consumed_tokens, "GIT_REHEARSAL_SINGLE_USE_ALREADY_CONSUMED")
        self.consumed_tokens.add(token)

    def create_blob(self, path: str, content: bytes) -> str:
        point = "blob:" + path
        self.calls.append(point)
        self._fail(point)
        sha = _git_blob_sha1(content)
        self.blobs[sha] = content
        return sha

    def create_tree(self, *, base_tree_sha: str, elements: list[dict[str, str]]) -> str:
        self.calls.append("tree")
        self._fail("tree")
        value = {"base_tree_sha": base_tree_sha, "elements": elements}
        sha = _synthetic_sha1("tree", value)
        self.trees[sha] = value
        return sha

    def create_commit(self, *, parent_sha: str, tree_sha: str, message: str) -> str:
        self.calls.append("commit")
        self._fail("commit")
        value = {"parent_sha": parent_sha, "tree_sha": tree_sha, "message": message}
        sha = _synthetic_sha1("commit", value)
        self.commits[sha] = value
        return sha

    def create_ref(self, *, branch: str, commit_sha: str) -> None:
        self.calls.append("ref:" + branch)
        self._fail("ref")
        require(branch not in self.refs, "GIT_REHEARSAL_BRANCH_ALREADY_EXISTS")
        self.refs[branch] = commit_sha


def rehearse_activation_git_transaction(
    transaction_plan: Mapping[str, Any],
    candidate_files: Mapping[str, str],
    backend: SyntheticGitBackend,
    *,
    expected_transaction_plan_sha256: str,
    expected_base_main_sha: str,
    expected_candidate_manifest_sha256: str,
) -> dict[str, Any]:
    require(
        type(backend) is SyntheticGitBackend
        and backend.transport == "SYNTHETIC_IN_MEMORY_ONLY",
        "GIT_REHEARSAL_REAL_BACKEND_FORBIDDEN",
    )
    plan_hash = _sha64(
        expected_transaction_plan_sha256,
        "GIT_REHEARSAL_EXPECTED_PLAN_HASH_INVALID",
    )
    base_main = _sha40(
        expected_base_main_sha,
        "GIT_REHEARSAL_EXPECTED_MAIN_INVALID",
    )
    manifest_hash = _sha64(
        expected_candidate_manifest_sha256,
        "GIT_REHEARSAL_EXPECTED_MANIFEST_HASH_INVALID",
    )

    require(isinstance(transaction_plan, Mapping), "GIT_REHEARSAL_PLAN_INVALID")
    require(
        canonical_digest(transaction_plan) == plan_hash,
        "GIT_REHEARSAL_PLAN_HASH_MISMATCH",
    )
    require(
        transaction_plan.get("artifact")
        == "RATE_INTRADAY_ACTIVATION_APPLY_TRANSACTION_PLAN_V1"
        and transaction_plan.get("status") == "TRANSACTION_PLAN_ONLY",
        "GIT_REHEARSAL_PLAN_STATUS_INVALID",
    )
    require(
        transaction_plan.get("base_main_sha") == base_main
        and backend.refs.get("main") == base_main,
        "GIT_REHEARSAL_MAIN_BINDING_MISMATCH",
    )
    require(
        transaction_plan.get("candidate_manifest_sha256") == manifest_hash,
        "GIT_REHEARSAL_MANIFEST_BINDING_MISMATCH",
    )
    require(
        transaction_plan.get("single_use") is True
        and transaction_plan.get("automatic_retry_allowed") is False
        and transaction_plan.get("fallback_allowed") is False
        and transaction_plan.get("merge_allowed_by_plan") is False
        and transaction_plan.get("direct_main_update_allowed") is False
        and transaction_plan.get("apply_executed") is False
        and transaction_plan.get("repository_writes") == 0
        and transaction_plan.get("live_provider_requests") == 0
        and transaction_plan.get("external_dependency_resolved") is False
        and transaction_plan.get("registry_activation_allowed") is False
        and transaction_plan.get("production_credit") == 0
        and transaction_plan.get("cer081_credit") == 0,
        "GIT_REHEARSAL_PLAN_BOUNDARY_INVALID",
    )

    require(
        isinstance(candidate_files, Mapping)
        and set(candidate_files) == set(EXPECTED_PATHS)
        and all(isinstance(v, str) and v for v in candidate_files.values()),
        "GIT_REHEARSAL_CANDIDATE_FILE_SET_INVALID",
    )
    require(
        candidate_manifest_sha256(candidate_files) == manifest_hash,
        "GIT_REHEARSAL_CANDIDATE_MANIFEST_HASH_MISMATCH",
    )

    file_plan = transaction_plan.get("files")
    require(
        isinstance(file_plan, Mapping)
        and set(file_plan) == set(EXPECTED_PATHS),
        "GIT_REHEARSAL_FILE_PLAN_INVALID",
    )
    for path in EXPECTED_PATHS:
        content = candidate_files[path].encode("utf-8")
        spec = file_plan[path]
        require(
            spec.get("mode") == "100644"
            and spec.get("content_sha256") == hashlib.sha256(content).hexdigest()
            and spec.get("git_blob_sha1") == _git_blob_sha1(content),
            "GIT_REHEARSAL_FILE_IDENTITY_MISMATCH:" + path,
        )

    branch = transaction_plan.get("target_branch")
    require(
        isinstance(branch, str)
        and branch.startswith("activation/rate-v11-intraday-")
        and branch != "main",
        "GIT_REHEARSAL_TARGET_BRANCH_INVALID",
    )
    # Replay is rejected by the single-use trust root before any branch-state
    # interpretation or synthetic mutation.
    require(
        plan_hash not in backend.consumed_tokens,
        "GIT_REHEARSAL_SINGLE_USE_ALREADY_CONSUMED",
    )
    require(branch not in backend.refs, "GIT_REHEARSAL_BRANCH_ALREADY_EXISTS")

    # Single-use is consumed before the first synthetic Git mutation. A later
    # failure is intentionally non-retryable.
    backend.consume(plan_hash)

    elements = []
    for path in EXPECTED_PATHS:
        content = candidate_files[path].encode("utf-8")
        blob_sha = backend.create_blob(path, content)
        require(
            blob_sha == file_plan[path]["git_blob_sha1"],
            "GIT_REHEARSAL_BLOB_SHA_MISMATCH:" + path,
        )
        elements.append({
            "path": path,
            "mode": "100644",
            "type": "blob",
            "sha": blob_sha,
        })

    tree_sha = backend.create_tree(
        base_tree_sha=backend.main_tree_sha,
        elements=elements,
    )
    message = (
        "RATE V11 intraday activation candidate "
        + transaction_plan["control_center_decision_id"]
    )
    commit_sha = backend.create_commit(
        parent_sha=base_main,
        tree_sha=tree_sha,
        message=message,
    )
    backend.create_ref(branch=branch, commit_sha=commit_sha)

    require(
        backend.refs.get("main") == base_main,
        "GIT_REHEARSAL_MAIN_REF_MUTATED",
    )
    require(
        backend.refs.get(branch) == commit_sha,
        "GIT_REHEARSAL_BRANCH_REF_MISSING",
    )
    require(
        backend.calls[-1] == "ref:" + branch,
        "GIT_REHEARSAL_BRANCH_REF_NOT_LAST",
    )

    return {
        "artifact": "RATE_INTRADAY_ACTIVATION_GIT_TRANSACTION_REHEARSAL_V1",
        "validation_status": "PASS",
        "transport": "SYNTHETIC_IN_MEMORY_ONLY",
        "transaction_plan_sha256": plan_hash,
        "base_main_sha": base_main,
        "candidate_manifest_sha256": manifest_hash,
        "synthetic_tree_sha": tree_sha,
        "synthetic_commit_sha": commit_sha,
        "synthetic_branch": branch,
        "blob_count": len(elements),
        "single_use_consumed": True,
        "retry_allowed": False,
        "main_ref_unchanged": True,
        "branch_ref_created_last": True,
        "real_git_objects_created": 0,
        "real_repository_writes": 0,
        "real_branch_created": False,
        "real_pull_request_created": False,
        "merge_performed": False,
        "live_provider_requests": 0,
        "external_dependency_resolved": False,
        "registry_activation_allowed": False,
        "production_credit": 0,
        "cer081_credit": 0,
        "next_gate": "EXPLICIT_REAL_GIT_TRANSACTION_EXECUTION_AUTHORIZATION",
    }

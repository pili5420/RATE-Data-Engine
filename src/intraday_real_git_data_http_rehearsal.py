"""Synthetic GitHub Git-Data HTTP rehearsal for one activation transaction.

No real GitHub request is performed. The rehearsal validates the exact main commit,
derives its immutable tree, creates 9 candidate blobs, one tree, one commit and one
activation branch ref, then reads the ref back.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from typing import Any, Mapping

from .intraday_activation_apply_authorization import EXPECTED_PATHS
from .intraday_activation_candidate_review import canonical_digest


class RealGitHTTPRehearsalError(RuntimeError):
    pass


class AmbiguousRefCreate(RuntimeError):
    pass


def require(condition: bool, reason: str) -> None:
    if not condition:
        raise RealGitHTTPRehearsalError(reason)


def candidate_manifest_sha256(candidate_files: Mapping[str, str]) -> str:
    require(
        isinstance(candidate_files, Mapping)
        and set(candidate_files) == set(EXPECTED_PATHS)
        and all(isinstance(v, str) and v for v in candidate_files.values()),
        "GIT_HTTP_CANDIDATE_FILE_SET_INVALID",
    )
    return canonical_digest({
        "artifact": "RATE_INTRADAY_ACTIVATION_CANDIDATE_FILE_MANIFEST_V1",
        "files": {
            path: hashlib.sha256(candidate_files[path].encode("utf-8")).hexdigest()
            for path in EXPECTED_PATHS
        },
    })


def _git_blob_sha1(content: bytes) -> str:
    return hashlib.sha1(
        f"blob {len(content)}\0".encode("ascii") + content
    ).hexdigest()


def _synthetic_sha(value: Any) -> str:
    return hashlib.sha1(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


class SyntheticGitDataHTTP:
    def __init__(self, *, main_sha: str, base_tree_sha: str, fail_at: str | None = None):
        self.main_sha = main_sha
        self.base_tree_sha = base_tree_sha
        self.fail_at = fail_at
        self.calls: list[dict[str, Any]] = []
        self.blobs: dict[str, str] = {}
        self.trees: dict[str, dict[str, Any]] = {}
        self.commits: dict[str, dict[str, Any]] = {
            main_sha: {"sha": main_sha, "tree": {"sha": base_tree_sha}}
        }
        self.refs: dict[str, str] = {"heads/main": main_sha}
        self.blob_attempts = 0
        self.tree_attempts = 0
        self.commit_attempts = 0
        self.ref_create_attempts = 0

    def request(self, method: str, path: str, *, body: Mapping[str, Any] | None = None):
        self.calls.append({"method": method, "path": path, "body": deepcopy(body)})

        if method == "GET" and path == "/repos/pili5420/RATE-Data-Engine/git/ref/heads/main":
            return 200, {"ref": "refs/heads/main", "object": {"sha": self.main_sha}}

        prefix = "/repos/pili5420/RATE-Data-Engine/git/commits/"
        if method == "GET" and path.startswith(prefix):
            sha = path[len(prefix):]
            if sha not in self.commits:
                return 404, {"message": "Not Found"}
            return 200, deepcopy(self.commits[sha])

        ref_prefix = "/repos/pili5420/RATE-Data-Engine/git/ref/heads/"
        if method == "GET" and path.startswith(ref_prefix):
            branch = path[len(ref_prefix):]
            key = "heads/" + branch
            if key not in self.refs:
                return 404, {"message": "Not Found"}
            return 200, {
                "ref": "refs/" + key,
                "object": {"sha": self.refs[key]},
            }

        if method == "POST" and path == "/repos/pili5420/RATE-Data-Engine/git/blobs":
            index = self.blob_attempts
            self.blob_attempts += 1
            if self.fail_at == f"blob:{index}":
                raise RuntimeError("SYNTHETIC_GIT_HTTP_BLOB_FAILED")
            content = str(body["content"])
            require(body.get("encoding") == "utf-8", "GIT_HTTP_BLOB_ENCODING_INVALID")
            sha = _git_blob_sha1(content.encode("utf-8"))
            self.blobs[sha] = content
            return 201, {"sha": sha}

        if method == "POST" and path == "/repos/pili5420/RATE-Data-Engine/git/trees":
            self.tree_attempts += 1
            if self.fail_at == "tree":
                raise RuntimeError("SYNTHETIC_GIT_HTTP_TREE_FAILED")
            require(body.get("base_tree") == self.base_tree_sha, "GIT_HTTP_BASE_TREE_INVALID")
            entries = body.get("tree")
            require(isinstance(entries, list) and len(entries) == 9, "GIT_HTTP_TREE_ENTRY_COUNT_INVALID")
            require(all(item.get("sha") in self.blobs for item in entries), "GIT_HTTP_TREE_UNKNOWN_BLOB")
            sha = _synthetic_sha({"base_tree": self.base_tree_sha, "tree": entries})
            self.trees[sha] = deepcopy(dict(body))
            return 201, {"sha": sha}

        if method == "POST" and path == "/repos/pili5420/RATE-Data-Engine/git/commits":
            self.commit_attempts += 1
            if self.fail_at == "commit":
                raise RuntimeError("SYNTHETIC_GIT_HTTP_COMMIT_FAILED")
            require(body.get("tree") in self.trees, "GIT_HTTP_COMMIT_TREE_INVALID")
            require(body.get("parents") == [self.main_sha], "GIT_HTTP_COMMIT_PARENT_INVALID")
            sha = _synthetic_sha(body)
            self.commits[sha] = {"sha": sha, "tree": {"sha": body["tree"]}}
            return 201, {"sha": sha}

        if method == "POST" and path == "/repos/pili5420/RATE-Data-Engine/git/refs":
            self.ref_create_attempts += 1
            if self.fail_at == "ref:before":
                raise RuntimeError("SYNTHETIC_GIT_HTTP_REF_FAILED_BEFORE_CREATE")
            ref = str(body["ref"])
            require(ref.startswith("refs/heads/activation/rate-v11-intraday-"), "GIT_HTTP_REF_INVALID")
            key = ref.removeprefix("refs/")
            require(key not in self.refs, "GIT_HTTP_REF_ALREADY_EXISTS")
            self.refs[key] = str(body["sha"])
            if self.fail_at == "ref:ambiguous":
                raise AmbiguousRefCreate("SYNTHETIC_GIT_HTTP_REF_AMBIGUOUS")
            return 201, {"ref": ref, "object": {"sha": body["sha"]}}

        raise RealGitHTTPRehearsalError("GIT_HTTP_REQUEST_SHAPE_FORBIDDEN")


def rehearse_real_git_data_http(
    transaction_plan: Mapping[str, Any],
    candidate_files: Mapping[str, str],
    transport: SyntheticGitDataHTTP,
    *,
    expected_transaction_plan_sha256: str,
    expected_base_main_sha: str,
    expected_candidate_manifest_sha256: str,
) -> dict[str, Any]:
    require(
        canonical_digest(transaction_plan) == expected_transaction_plan_sha256,
        "GIT_HTTP_PLAN_HASH_MISMATCH",
    )
    require(
        transaction_plan.get("artifact")
        == "RATE_INTRADAY_ACTIVATION_APPLY_TRANSACTION_PLAN_V1"
        and transaction_plan.get("status") == "TRANSACTION_PLAN_ONLY",
        "GIT_HTTP_PLAN_NOT_VALID",
    )
    require(
        transaction_plan.get("base_main_sha") == expected_base_main_sha,
        "GIT_HTTP_PLAN_MAIN_MISMATCH",
    )
    require(
        candidate_manifest_sha256(candidate_files)
        == expected_candidate_manifest_sha256
        == transaction_plan.get("candidate_manifest_sha256"),
        "GIT_HTTP_CANDIDATE_MANIFEST_MISMATCH",
    )
    require(
        isinstance(candidate_files, Mapping)
        and set(candidate_files) == set(EXPECTED_PATHS),
        "GIT_HTTP_CANDIDATE_FILE_SET_INVALID",
    )
    require(type(transport) is SyntheticGitDataHTTP, "GIT_HTTP_REAL_TRANSPORT_FORBIDDEN_IN_CI")

    branch = transaction_plan["target_branch"]
    require(
        isinstance(branch, str)
        and branch.startswith("activation/rate-v11-intraday-"),
        "GIT_HTTP_BRANCH_INVALID",
    )

    status, main_ref = transport.request(
        "GET", "/repos/pili5420/RATE-Data-Engine/git/ref/heads/main"
    )
    require(status == 200 and main_ref["object"]["sha"] == expected_base_main_sha,
            "GIT_HTTP_MAIN_REF_DRIFT")

    status, commit_object = transport.request(
        "GET",
        "/repos/pili5420/RATE-Data-Engine/git/commits/" + expected_base_main_sha,
    )
    require(status == 200, "GIT_HTTP_BASE_COMMIT_MISSING")
    base_tree = commit_object.get("tree", {}).get("sha")
    require(isinstance(base_tree, str) and len(base_tree) == 40, "GIT_HTTP_BASE_TREE_INVALID")

    branch_path = "/repos/pili5420/RATE-Data-Engine/git/ref/heads/" + branch
    status, _ = transport.request("GET", branch_path)
    require(status == 404, "GIT_HTTP_TARGET_BRANCH_ALREADY_EXISTS")

    blob_shas: dict[str, str] = {}
    file_plan = transaction_plan["files"]
    for path in EXPECTED_PATHS:
        content = candidate_files[path]
        status, blob = transport.request(
            "POST",
            "/repos/pili5420/RATE-Data-Engine/git/blobs",
            body={"content": content, "encoding": "utf-8"},
        )
        require(status == 201, "GIT_HTTP_BLOB_CREATE_STATUS_INVALID")
        sha = blob["sha"]
        require(
            sha == file_plan[path]["git_blob_sha1"]
            == _git_blob_sha1(content.encode("utf-8")),
            "GIT_HTTP_BLOB_SHA_MISMATCH:" + path,
        )
        blob_shas[path] = sha

    tree_entries = [
        {"path": path, "mode": "100644", "type": "blob", "sha": blob_shas[path]}
        for path in EXPECTED_PATHS
    ]
    status, tree = transport.request(
        "POST",
        "/repos/pili5420/RATE-Data-Engine/git/trees",
        body={"base_tree": base_tree, "tree": tree_entries},
    )
    require(status == 201, "GIT_HTTP_TREE_CREATE_STATUS_INVALID")

    status, commit = transport.request(
        "POST",
        "/repos/pili5420/RATE-Data-Engine/git/commits",
        body={
            "message": "RATE V11 Intraday Activation Candidate",
            "tree": tree["sha"],
            "parents": [expected_base_main_sha],
        },
    )
    require(status == 201, "GIT_HTTP_COMMIT_CREATE_STATUS_INVALID")
    commit_sha = commit["sha"]

    try:
        status, created_ref = transport.request(
            "POST",
            "/repos/pili5420/RATE-Data-Engine/git/refs",
            body={"ref": "refs/heads/" + branch, "sha": commit_sha},
        )
        require(
            status == 201 and created_ref["object"]["sha"] == commit_sha,
            "GIT_HTTP_REF_CREATE_STATUS_INVALID",
        )
    except AmbiguousRefCreate:
        status2, ref2 = transport.request("GET", branch_path)
        require(
            status2 == 200 and ref2["object"]["sha"] == commit_sha,
            "GIT_HTTP_REF_AMBIGUOUS_UNRESOLVED",
        )

    status, readback = transport.request("GET", branch_path)
    require(
        status == 200 and readback["object"]["sha"] == commit_sha,
        "GIT_HTTP_REF_READBACK_MISMATCH",
    )
    require(
        transport.blob_attempts == 9
        and transport.tree_attempts == 1
        and transport.commit_attempts == 1
        and transport.ref_create_attempts == 1,
        "GIT_HTTP_OPERATION_BUDGET_INVALID",
    )

    return {
        "artifact": "RATE_REAL_GIT_DATA_HTTP_EXECUTOR_REHEARSAL_V1",
        "validation_status": "PASS",
        "transaction_plan_sha256": expected_transaction_plan_sha256,
        "base_main_sha": expected_base_main_sha,
        "base_tree_sha": base_tree,
        "candidate_manifest_sha256": expected_candidate_manifest_sha256,
        "target_branch": branch,
        "commit_sha": commit_sha,
        "blob_count": 9,
        "tree_count": 1,
        "commit_count": 1,
        "ref_create_count": 1,
        "ref_create_retries": 0,
        "branch_readback_verified": True,
        "main_ref_unchanged": transport.refs["heads/main"] == expected_base_main_sha,
        "real_github_requests": 0,
        "real_git_operations": 0,
        "real_branch_created": False,
        "production_credit": 0,
        "cer081_credit": 0,
        "next_gate": "REAL_GIT_TRANSACTION_EXECUTION_READINESS",
    }

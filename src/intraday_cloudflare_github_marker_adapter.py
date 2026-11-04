"""Synthetic qualification for the GitHub ref adapter used by Cloudflare qualification consumption markers.

No real GitHub request is performed. The adapter semantics are exercised against a
fake exact-path transport.
"""
from __future__ import annotations

from copy import deepcopy
import re
from typing import Any, Mapping

REF_PREFIX = "refs/tags/rate-v11-qualification-consumed/cloudflare-d1-"
HEX40 = re.compile(r"^[0-9a-f]{40}$")
HEX64 = re.compile(r"^[0-9a-f]{64}$")


class GitHubMarkerAdapterError(RuntimeError):
    pass


class AmbiguousGitHubCreate(RuntimeError):
    pass


def require(condition: bool, reason: str) -> None:
    if not condition:
        raise GitHubMarkerAdapterError(reason)


def marker_ref(authorization_sha256: str) -> str:
    value = str(authorization_sha256 or "").lower()
    require(bool(HEX64.fullmatch(value)), "GH_MARKER_AUTH_HASH_INVALID")
    return REF_PREFIX + value[:16]


class SyntheticGitHubRefTransport:
    def __init__(self, *, fail_mode: str | None = None):
        self.refs: dict[str, str] = {}
        self.fail_mode = fail_mode
        self.calls: list[dict[str, Any]] = []

    def request(self, method: str, path: str, *, token: str, json_body: Mapping[str, Any] | None = None):
        self.calls.append({"method": method, "path": path, "body": deepcopy(json_body)})
        require(token == "synthetic-token", "GH_MARKER_TOKEN_SCOPE_INVALID")
        if method == "POST" and path == "/repos/pili5420/RATE-Data-Engine/git/refs":
            if self.fail_mode == "BEFORE_CREATE":
                raise RuntimeError("SYNTHETIC_GITHUB_FAIL_BEFORE_CREATE")
            ref = json_body["ref"]
            sha = json_body["sha"]
            if ref in self.refs:
                return 422, {"message": "Reference already exists"}
            self.refs[ref] = sha
            if self.fail_mode == "AMBIGUOUS_AFTER_CREATE":
                raise AmbiguousGitHubCreate("SYNTHETIC_GITHUB_AMBIGUOUS_AFTER_CREATE")
            return 201, {"ref": ref, "object": {"sha": sha}}
        if method == "GET" and path.startswith("/repos/pili5420/RATE-Data-Engine/git/ref/"):
            ref = path.split("/git/ref/", 1)[1]
            full = "refs/" + ref
            if full not in self.refs:
                return 404, {"message": "Not Found"}
            return 200, {"ref": full, "object": {"sha": self.refs[full]}}
        raise GitHubMarkerAdapterError("GH_MARKER_REQUEST_SHAPE_FORBIDDEN")


def qualify_marker_adapter(
    transport: SyntheticGitHubRefTransport,
    *,
    authorization_sha256: str,
    current_main_sha: str,
    token: str = "synthetic-token",
) -> dict[str, Any]:
    require(type(transport) is SyntheticGitHubRefTransport, "GH_MARKER_REAL_TRANSPORT_FORBIDDEN")
    main = str(current_main_sha or "").lower()
    require(bool(HEX40.fullmatch(main)), "GH_MARKER_MAIN_SHA_INVALID")
    ref = marker_ref(authorization_sha256)
    require(ref.startswith(REF_PREFIX) and ref != "refs/heads/main", "GH_MARKER_REF_INVALID")

    get_path = "/repos/pili5420/RATE-Data-Engine/git/ref/" + ref.removeprefix("refs/")
    status, body = transport.request("GET", get_path, token=token)
    if status == 200:
        require(body["object"]["sha"] == main, "GH_MARKER_EXISTING_TARGET_CONFLICT")
        raise GitHubMarkerAdapterError("GH_MARKER_ALREADY_CONSUMED")
    require(status == 404, "GH_MARKER_PREFLIGHT_READ_INVALID")

    try:
        status, body = transport.request(
            "POST",
            "/repos/pili5420/RATE-Data-Engine/git/refs",
            token=token,
            json_body={"ref": ref, "sha": main},
        )
    except AmbiguousGitHubCreate:
        status2, body2 = transport.request("GET", get_path, token=token)
        require(status2 == 200, "GH_MARKER_AMBIGUOUS_CREATE_UNRESOLVED")
        require(body2["object"]["sha"] == main, "GH_MARKER_AMBIGUOUS_TARGET_CONFLICT")
        return {
            "validation_status": "PASS",
            "outcome": "AMBIGUOUS_CREATE_CONFIRMED_BY_READBACK",
            "marker_ref": ref,
            "marker_target_sha": main,
            "create_attempts": sum(c["method"] == "POST" for c in transport.calls),
            "create_retries": 0,
            "real_github_requests": 0,
            "real_git_ref_created": False,
        }

    require(status == 201 and body["object"]["sha"] == main, "GH_MARKER_CREATE_INVALID")
    status2, body2 = transport.request("GET", get_path, token=token)
    require(status2 == 200 and body2["object"]["sha"] == main, "GH_MARKER_READBACK_MISMATCH")
    return {
        "validation_status": "PASS",
        "outcome": "CREATED_AND_READBACK_VERIFIED",
        "marker_ref": ref,
        "marker_target_sha": main,
        "create_attempts": sum(c["method"] == "POST" for c in transport.calls),
        "create_retries": 0,
        "real_github_requests": 0,
        "real_git_ref_created": False,
    }

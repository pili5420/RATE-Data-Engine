"""Synthetic HTTP rehearsal for one authorized real Draft activation PR creation.

No real GitHub request is performed. The rehearsal models the exact GET/POST REST
surface and ambiguous-create readback using a fake HTTP transport.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping
from urllib.parse import quote

from .intraday_activation_candidate_review import canonical_digest


class DraftPRHTTPRehearsalError(RuntimeError):
    pass


class AmbiguousPOSTOutcome(RuntimeError):
    pass


def require(condition: bool, reason: str) -> None:
    if not condition:
        raise DraftPRHTTPRehearsalError(reason)


class SyntheticGitHubPRHTTP:
    def __init__(self, *, fail_mode: str | None = None):
        self.fail_mode = fail_mode
        self.calls: list[dict[str, Any]] = []
        self.prs: list[dict[str, Any]] = []

    def request(self, method: str, path: str, *, body: Mapping[str, Any] | None = None):
        self.calls.append({"method": method, "path": path, "body": deepcopy(body)})
        if method == "GET" and path.startswith(
            "/repos/pili5420/RATE-Data-Engine/pulls?state=open&head="
        ):
            query = path.split("?", 1)[1]
            values = {}
            for part in query.split("&"):
                key, value = part.split("=", 1)
                values[key] = value
            head = values["head"].split(":", 1)[1]
            base = values["base"]
            found = [
                deepcopy(pr)
                for pr in self.prs
                if pr["head"] == head and pr["base"] == base and pr["state"] == "open"
            ]
            return 200, found

        if method == "POST" and path == "/repos/pili5420/RATE-Data-Engine/pulls":
            if self.fail_mode == "BEFORE_CREATE":
                raise RuntimeError("SYNTHETIC_GITHUB_PR_FAIL_BEFORE_CREATE")
            if not isinstance(body, Mapping):
                return 422, {"message": "invalid"}
            number = len(self.prs) + 1
            pr = {
                "number": number,
                "state": "open",
                "title": body["title"],
                "body": body["body"],
                "head": body["head"],
                "base": body["base"],
                "draft": body["draft"],
            }
            self.prs.append(deepcopy(pr))
            if self.fail_mode == "AMBIGUOUS_AFTER_CREATE":
                raise AmbiguousPOSTOutcome("SYNTHETIC_GITHUB_PR_AMBIGUOUS_AFTER_CREATE")
            return 201, deepcopy(pr)

        raise DraftPRHTTPRehearsalError("DRAFT_PR_HTTP_REQUEST_SHAPE_FORBIDDEN")


def _marker_body(*, receipt_sha256: str, execution_authorization_sha256: str) -> str:
    return (
        "RATE V11 Intraday Activation Candidate\n\n"
        f"RATE-Activation-Receipt-SHA256: {receipt_sha256}\n"
        f"RATE-Draft-PR-Execution-Authorization-SHA256: {execution_authorization_sha256}\n"
        "State: DRAFT_ONLY\n"
        "Do not mark ready or merge without separate authorization.\n"
    )


def _query_path(head: str) -> str:
    return (
        "/repos/pili5420/RATE-Data-Engine/pulls"
        "?state=open&head=pili5420:" + quote(head, safe="/-._") + "&base=main"
    )


def _matching(pr: Mapping[str, Any], *, head: str, receipt: str, auth_hash: str) -> bool:
    body = str(pr.get("body") or "")
    return (
        pr.get("head") == head
        and pr.get("base") == "main"
        and pr.get("draft") is True
        and f"RATE-Activation-Receipt-SHA256: {receipt}" in body
        and f"RATE-Draft-PR-Execution-Authorization-SHA256: {auth_hash}" in body
    )


def rehearse_draft_pr_http_execution(
    execution_authorization: Mapping[str, Any],
    transport: SyntheticGitHubPRHTTP,
    *,
    expected_execution_authorization_sha256: str,
) -> dict[str, Any]:
    require(
        canonical_digest(execution_authorization)
        == expected_execution_authorization_sha256,
        "DRAFT_PR_HTTP_AUTH_HASH_MISMATCH",
    )
    require(
        execution_authorization.get("artifact")
        == "RATE_REAL_DRAFT_PR_TRANSPORT_EXECUTION_AUTHORIZATION_QUALIFICATION_V1"
        and execution_authorization.get("validation_status") == "PASS",
        "DRAFT_PR_HTTP_AUTH_NOT_PASS",
    )
    require(
        execution_authorization.get("single_use") is True
        and execution_authorization.get("execution_consumed") is False
        and execution_authorization.get("create_attempts") == 1
        and execution_authorization.get("automatic_retry_allowed") is False
        and execution_authorization.get("fallback_allowed") is False,
        "DRAFT_PR_HTTP_SINGLE_USE_BOUNDARY_INVALID",
    )
    require(
        type(transport) is SyntheticGitHubPRHTTP,
        "DRAFT_PR_HTTP_REAL_TRANSPORT_FORBIDDEN_IN_CI",
    )

    head = execution_authorization["head"]
    receipt = execution_authorization["receipt_sha256"]
    require(
        isinstance(head, str) and head.startswith("activation/rate-v11-intraday-"),
        "DRAFT_PR_HTTP_HEAD_INVALID",
    )

    query = _query_path(head)
    status, existing = transport.request("GET", query)
    require(status == 200 and isinstance(existing, list), "DRAFT_PR_HTTP_PREFLIGHT_INVALID")
    if existing:
        require(len(existing) == 1, "DRAFT_PR_HTTP_MULTIPLE_EXISTING_PRS")
        if _matching(
            existing[0],
            head=head,
            receipt=receipt,
            auth_hash=expected_execution_authorization_sha256,
        ):
            raise DraftPRHTTPRehearsalError("DRAFT_PR_HTTP_ALREADY_CONSUMED")
        raise DraftPRHTTPRehearsalError("DRAFT_PR_HTTP_EXISTING_PR_CONFLICT")

    body_text = _marker_body(
        receipt_sha256=receipt,
        execution_authorization_sha256=expected_execution_authorization_sha256,
    )
    request_body = {
        "title": "RATE V11 Intraday Activation Candidate",
        "head": head,
        "base": "main",
        "draft": True,
        "body": body_text,
    }

    try:
        status2, created = transport.request(
            "POST",
            "/repos/pili5420/RATE-Data-Engine/pulls",
            body=request_body,
        )
    except AmbiguousPOSTOutcome:
        status3, found = transport.request("GET", query)
        require(status3 == 200 and len(found) == 1, "DRAFT_PR_HTTP_AMBIGUOUS_UNRESOLVED")
        require(
            _matching(
                found[0],
                head=head,
                receipt=receipt,
                auth_hash=expected_execution_authorization_sha256,
            ),
            "DRAFT_PR_HTTP_AMBIGUOUS_RESULT_CONFLICT",
        )
        return {
            "artifact": "RATE_DRAFT_PR_HTTP_EXECUTOR_REHEARSAL_V1",
            "validation_status": "PASS",
            "outcome": "AMBIGUOUS_CREATE_CONFIRMED_BY_READBACK",
            "head": head,
            "base": "main",
            "draft": True,
            "receipt_sha256": receipt,
            "execution_authorization_sha256":
                expected_execution_authorization_sha256,
            "post_attempts": sum(c["method"] == "POST" for c in transport.calls),
            "post_retries": 0,
            "real_github_requests": 0,
            "real_pull_request_created": False,
            "production_credit": 0,
            "cer081_credit": 0,
        }

    require(status2 == 201, "DRAFT_PR_HTTP_CREATE_STATUS_INVALID")
    require(
        _matching(
            created,
            head=head,
            receipt=receipt,
            auth_hash=expected_execution_authorization_sha256,
        ),
        "DRAFT_PR_HTTP_CREATE_RESULT_BINDING_INVALID",
    )
    return {
        "artifact": "RATE_DRAFT_PR_HTTP_EXECUTOR_REHEARSAL_V1",
        "validation_status": "PASS",
        "outcome": "CREATED",
        "head": head,
        "base": "main",
        "draft": True,
        "receipt_sha256": receipt,
        "execution_authorization_sha256": expected_execution_authorization_sha256,
        "post_attempts": 1,
        "post_retries": 0,
        "real_github_requests": 0,
        "real_pull_request_created": False,
        "production_credit": 0,
        "cer081_credit": 0,
        "next_gate": "REAL_DRAFT_PR_EXECUTION_READINESS",
    }

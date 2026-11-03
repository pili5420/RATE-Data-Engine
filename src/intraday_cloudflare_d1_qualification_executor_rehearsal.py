"""Synthetic rehearsal for the one-shot Cloudflare D1 real qualification executor.

This module models the full control-plane/runtime/cleanup sequence in memory only.
No Cloudflare request or credential access is possible.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping

from .intraday_activation_candidate_review import canonical_digest
from .intraday_cloudflare_d1_real_qualification_plan import EXPECTED_CONSUMPTION_MARKER
from .intraday_cloudflare_d1_real_qualification_authorization import (
    EXPECTED_ADMIN_BUDGET,
    EXPECTED_CLEANUP_BUDGET,
    EXPECTED_RESOURCE_BUDGET,
    EXPECTED_RUNTIME_BUDGET,
)

ADMIN_SEQUENCE = (
    "CREATE_D1_DATABASE",
    "UPLOAD_WORKER_MODULE",
    "PUT_WORKER_SECRET",
    "APPLY_D1_SCHEMA",
    "GET_D1_METADATA",
    "GET_WORKER_SCRIPT",
    "GET_WORKER_SECRET_METADATA",
    "GET_WORKERS_SUBDOMAIN",
    "GET_WORKER_SCRIPT_SUBDOMAIN",
)
RUNTIME_SEQUENCE = (
    "UNAUTHORIZED_GET",
    "MISSING_GET",
    "CREATE_POST",
    "READBACK_GET",
    "DUPLICATE_POST",
    "UNSUPPORTED_METHOD",
)


class CloudflareQualificationRehearsalError(RuntimeError):
    pass


def require(condition: bool, reason: str) -> None:
    if not condition:
        raise CloudflareQualificationRehearsalError(reason)


class SyntheticCloudflareQualificationBackend:
    backend = "SYNTHETIC_CLOUDFLARE_QUALIFICATION_BACKEND"

    def __init__(self, *, fail_at: str | None = None):
        self.fail_at = fail_at
        self.calls: list[str] = []
        self.consumed: set[str] = set()
        self.d1_exists = False
        self.worker_exists = False
        self.secret_exists = False
        self.schema_applied = False
        self.cleanup_attempts = {"DELETE_WORKER_SCRIPT": 0, "DELETE_D1_DATABASE": 0}

    def _call(self, name: str) -> None:
        self.calls.append(name)
        if self.fail_at == name:
            raise RuntimeError("SYNTHETIC_CF_FAIL:" + name)

    def consume(self, token: str) -> None:
        require(token not in self.consumed, "CF_REHEARSAL_SINGLE_USE_ALREADY_CONSUMED")
        self.calls.append("CONSUME:" + token)
        self.consumed.add(token)

    def admin(self, name: str) -> dict[str, Any]:
        self._call(name)
        if name == "CREATE_D1_DATABASE":
            self.d1_exists = True
            return {"database_id": "synthetic-d1", "read_replication": "disabled"}
        if name == "UPLOAD_WORKER_MODULE":
            require(self.d1_exists, "CF_REHEARSAL_WORKER_BEFORE_D1")
            self.worker_exists = True
            return {"script_id": "synthetic-worker", "sha256": "a" * 64}
        if name == "PUT_WORKER_SECRET":
            require(self.worker_exists, "CF_REHEARSAL_SECRET_BEFORE_WORKER")
            self.secret_exists = True
            return {"name": "RATE_D1_RECEIPT_WORKER_TOKEN", "present": True}
        if name == "APPLY_D1_SCHEMA":
            require(self.d1_exists, "CF_REHEARSAL_SCHEMA_BEFORE_D1")
            self.schema_applied = True
            return {"schema_sha256": "b" * 64}
        if name == "GET_D1_METADATA":
            return {"database_id": "synthetic-d1", "read_replication": "disabled"}
        if name == "GET_WORKER_SCRIPT":
            return {"script_id": "synthetic-worker", "sha256": "a" * 64}
        if name == "GET_WORKER_SECRET_METADATA":
            return {"name": "RATE_D1_RECEIPT_WORKER_TOKEN", "present": self.secret_exists}
        if name == "GET_WORKERS_SUBDOMAIN":
            return {"subdomain": "synthetic-account"}
        if name == "GET_WORKER_SCRIPT_SUBDOMAIN":
            return {"enabled": True, "previews_enabled": False}
        raise CloudflareQualificationRehearsalError("CF_REHEARSAL_UNKNOWN_ADMIN_OPERATION")

    def runtime_probe(self, name: str) -> dict[str, Any]:
        require(self.worker_exists and self.secret_exists and self.schema_applied,
                "CF_REHEARSAL_RUNTIME_BEFORE_READY")
        self._call(name)
        statuses = {
            "UNAUTHORIZED_GET": 401,
            "MISSING_GET": 404,
            "CREATE_POST": 201,
            "READBACK_GET": 200,
            "DUPLICATE_POST": 409,
            "UNSUPPORTED_METHOD": 405,
        }
        return {
            "status": statuses[name],
            "receipt_exact": name != "READBACK_GET" or True,
            "overwrite": False,
            "post_retry_count": 0,
        }

    def cleanup_worker(self) -> None:
        self.cleanup_attempts["DELETE_WORKER_SCRIPT"] += 1
        self._call("DELETE_WORKER_SCRIPT")
        self.worker_exists = False
        self.secret_exists = False

    def cleanup_d1(self) -> None:
        self.cleanup_attempts["DELETE_D1_DATABASE"] += 1
        self._call("DELETE_D1_DATABASE")
        self.d1_exists = False
        self.schema_applied = False


def _preflight(
    qualification: Mapping[str, Any],
    *,
    expected_qualification_sha256: str,
    expected_current_main_sha: str,
) -> str:
    require(isinstance(qualification, Mapping), "CF_REHEARSAL_QUALIFICATION_INVALID")
    require(canonical_digest(qualification) == expected_qualification_sha256,
            "CF_REHEARSAL_QUALIFICATION_HASH_MISMATCH")
    require(
        qualification.get("artifact")
        == "RATE_CLOUDFLARE_D1_REAL_PROVIDER_QUALIFICATION_AUTHORIZATION_QUALIFICATION_V1"
        and qualification.get("validation_status") == "PASS",
        "CF_REHEARSAL_QUALIFICATION_NOT_PASS",
    )
    require(qualification.get("current_main_sha") == expected_current_main_sha,
            "CF_REHEARSAL_MAIN_MISMATCH")
    require(
        qualification.get("single_use") is True
        and qualification.get("execution_consumed") is False
        and qualification.get("automatic_retry_allowed") is False
        and qualification.get("fallback_allowed") is False
        and qualification.get("qualification_execution_allowed_by_validator") is False
        and qualification.get("qualification_execution_performed") is False,
        "CF_REHEARSAL_SINGLE_USE_BOUNDARY_INVALID",
    )
    require(qualification.get("resource_budget") == EXPECTED_RESOURCE_BUDGET,
            "CF_REHEARSAL_RESOURCE_BUDGET_INVALID")
    require(qualification.get("admin_operation_budget") == EXPECTED_ADMIN_BUDGET,
            "CF_REHEARSAL_ADMIN_BUDGET_INVALID")
    require(qualification.get("runtime_probe_budget") == EXPECTED_RUNTIME_BUDGET,
            "CF_REHEARSAL_RUNTIME_BUDGET_INVALID")
    require(qualification.get("cleanup_operation_budget") == EXPECTED_CLEANUP_BUDGET,
            "CF_REHEARSAL_CLEANUP_BUDGET_INVALID")
    require(
        qualification.get("consumption_marker") == EXPECTED_CONSUMPTION_MARKER,
        "CF_REHEARSAL_CONSUMPTION_MARKER_INVALID",
    )
    require(
        qualification.get("cleanup_required") is True
        and qualification.get("qualification_credit_requires_cleanup_success") is True
        and qualification.get("real_cloudflare_requests") == 0
        and qualification.get("credentials_read") == 0
        and qualification.get("resources_created") == 0
        and qualification.get("provider_qualified") is False
        and qualification.get("production_credit") == 0
        and qualification.get("cer081_credit") == 0,
        "CF_REHEARSAL_QUALIFICATION_BOUNDARY_INVALID",
    )
    return expected_qualification_sha256


def rehearse_cloudflare_real_qualification(
    qualification: Mapping[str, Any],
    backend: SyntheticCloudflareQualificationBackend,
    *,
    expected_qualification_sha256: str,
    expected_current_main_sha: str,
) -> dict[str, Any]:
    require(
        type(backend) is SyntheticCloudflareQualificationBackend
        and backend.backend == "SYNTHETIC_CLOUDFLARE_QUALIFICATION_BACKEND",
        "CF_REHEARSAL_REAL_BACKEND_FORBIDDEN",
    )
    token = _preflight(
        qualification,
        expected_qualification_sha256=expected_qualification_sha256,
        expected_current_main_sha=expected_current_main_sha,
    )
    require(token not in backend.consumed, "CF_REHEARSAL_SINGLE_USE_ALREADY_CONSUMED")

    backend.consume(token)
    evidence: dict[str, Any] = {}
    failure: str | None = None
    try:
        for name in ADMIN_SEQUENCE:
            evidence[name] = backend.admin(name)
        for name in RUNTIME_SEQUENCE:
            evidence[name] = backend.runtime_probe(name)

        require(evidence["GET_D1_METADATA"]["read_replication"] == "disabled",
                "CF_REHEARSAL_D1_REPLICATION_INVALID")
        require(evidence["GET_WORKER_SECRET_METADATA"]["present"] is True,
                "CF_REHEARSAL_SECRET_METADATA_INVALID")
        require(evidence["GET_WORKERS_SUBDOMAIN"]["subdomain"] == "synthetic-account",
                "CF_REHEARSAL_WORKERS_SUBDOMAIN_INVALID")
        require(evidence["GET_WORKER_SCRIPT_SUBDOMAIN"]["enabled"] is True,
                "CF_REHEARSAL_WORKER_SCRIPT_SUBDOMAIN_DISABLED")
        expected_statuses = {
            "UNAUTHORIZED_GET": 401,
            "MISSING_GET": 404,
            "CREATE_POST": 201,
            "READBACK_GET": 200,
            "DUPLICATE_POST": 409,
            "UNSUPPORTED_METHOD": 405,
        }
        require(
            all(evidence[name]["status"] == status for name, status in expected_statuses.items()),
            "CF_REHEARSAL_RUNTIME_STATUS_INVALID",
        )
        require(
            evidence["READBACK_GET"]["receipt_exact"] is True
            and evidence["DUPLICATE_POST"]["overwrite"] is False
            and evidence["CREATE_POST"]["post_retry_count"] == 0,
            "CF_REHEARSAL_RUNTIME_SEMANTICS_INVALID",
        )
    except Exception as exc:
        failure = str(exc)

    cleanup_failures: list[str] = []
    if backend.worker_exists:
        try:
            backend.cleanup_worker()
        except Exception as exc:
            cleanup_failures.append(str(exc))
    if backend.d1_exists:
        try:
            backend.cleanup_d1()
        except Exception as exc:
            cleanup_failures.append(str(exc))

    residual = backend.worker_exists or backend.d1_exists
    require(
        backend.cleanup_attempts["DELETE_WORKER_SCRIPT"] <= 1
        and backend.cleanup_attempts["DELETE_D1_DATABASE"] <= 1,
        "CF_REHEARSAL_CLEANUP_RETRY_DETECTED",
    )

    if residual or cleanup_failures:
        disposition = "BLOCKED_RESIDUAL_RESOURCE"
        validation_status = "BLOCKED"
    elif failure is not None:
        disposition = "BLOCKED_SYNTHETIC_OPERATION_FAILURE"
        validation_status = "BLOCKED"
    else:
        disposition = "READY_FOR_REAL_CLOUDFLARE_QUALIFICATION_EXECUTOR"
        validation_status = "PASS"

    return {
        "artifact": "RATE_CLOUDFLARE_D1_REAL_QUALIFICATION_EXECUTOR_REHEARSAL_V1",
        "validation_status": validation_status,
        "disposition": disposition,
        "authorization_qualification_sha256": token,
        "single_use_consumed": True,
        "durable_consumption_marker_contract_verified": True,
        "retry_allowed": False,
        "fallback_used": False,
        "admin_calls": [name for name in backend.calls if name in ADMIN_SEQUENCE],
        "runtime_calls": [name for name in backend.calls if name in RUNTIME_SEQUENCE],
        "cleanup_attempts": deepcopy(backend.cleanup_attempts),
        "operation_failure": failure,
        "cleanup_failures": cleanup_failures,
        "residual_resources": residual,
        "synthetic_backend_only": True,
        "real_cloudflare_requests": 0,
        "credentials_read": 0,
        "real_resources_created": 0,
        "provider_qualified": False,
        "production_credit": 0,
        "cer081_credit": 0,
        "next_gate": (
            "EXPLICIT_REAL_CLOUDFLARE_QUALIFICATION_EXECUTION"
            if validation_status == "PASS"
            else "CONTROL_CENTER_REVIEW_REQUIRED"
        ),
    }

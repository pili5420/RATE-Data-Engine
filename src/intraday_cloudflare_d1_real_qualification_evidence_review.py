"""Pure review gate for a completed real Cloudflare D1 qualification evidence package.

The validator performs no network request. It binds one exact real execution package,
required evidence-object hashes, runtime statuses and cleanup proof before Control
Center provider acceptance may be considered.
"""
from __future__ import annotations

from urllib.parse import urlparse
import re
from typing import Any, Mapping

from .intraday_activation_candidate_review import canonical_digest
from .intraday_cloudflare_d1_real_qualification_plan import (
    ADMIN_OPERATIONS,
    CLEANUP_OPERATIONS,
    RUNTIME_PROBES,
)

HEX40 = re.compile(r"^[0-9a-f]{40}$")
HEX64 = re.compile(r"^[0-9a-f]{64}$")
UUID = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
)
REQUIRED_RESULT_EVIDENCE = {
    "D1_DATABASE_ID",
    "D1_READ_REPLICATION_DISABLED",
    "WORKER_SCRIPT_ID",
    "WORKER_SCRIPT_SHA256",
    "WORKER_SECRET_METADATA_PRESENT",
    "WORKERS_DEV_ENDPOINT",
    "SCHEMA_SHA256",
    "RUNTIME_PROBE_RESULTS",
    "CLEANUP_WORKER_DELETED",
    "CLEANUP_D1_DELETED",
}
EXPECTED_RUNTIME_STATUSES = {
    "UNAUTHORIZED_GET": 401,
    "MISSING_GET": 404,
    "CREATE_POST": 201,
    "READBACK_GET": 200,
    "DUPLICATE_POST": 409,
    "UNSUPPORTED_METHOD": 405,
}


class CloudflareEvidenceReviewError(RuntimeError):
    pass


def require(condition: bool, reason: str) -> None:
    if not condition:
        raise CloudflareEvidenceReviewError(reason)


def _sha40(value: Any, reason: str) -> str:
    text = str(value or "").lower()
    require(bool(HEX40.fullmatch(text)), reason)
    return text


def _sha64(value: Any, reason: str) -> str:
    text = str(value or "").lower()
    require(bool(HEX64.fullmatch(text)), reason)
    return text


def _positive_int(value: Any, reason: str) -> int:
    require(isinstance(value, int) and not isinstance(value, bool) and value > 0, reason)
    return value


def validate_cloudflare_real_qualification_evidence(
    package: Mapping[str, Any],
    *,
    expected_package_sha256: str,
    expected_evidence_manifest_sha256: str,
    expected_cloudflare_authorization_qualification_sha256: str,
    expected_marker_execution_result_sha256: str,
    expected_current_main_sha: str,
    expected_workflow_run_id: int,
    expected_workflow_job_id: int,
) -> dict[str, Any]:
    package_hash = _sha64(
        expected_package_sha256,
        "CF_EVIDENCE_EXPECTED_PACKAGE_HASH_INVALID",
    )
    evidence_hash = _sha64(
        expected_evidence_manifest_sha256,
        "CF_EVIDENCE_EXPECTED_MANIFEST_HASH_INVALID",
    )
    auth_hash = _sha64(
        expected_cloudflare_authorization_qualification_sha256,
        "CF_EVIDENCE_EXPECTED_AUTH_HASH_INVALID",
    )
    marker_hash = _sha64(
        expected_marker_execution_result_sha256,
        "CF_EVIDENCE_EXPECTED_MARKER_HASH_INVALID",
    )
    main = _sha40(expected_current_main_sha, "CF_EVIDENCE_EXPECTED_MAIN_INVALID")
    run_id = _positive_int(expected_workflow_run_id, "CF_EVIDENCE_EXPECTED_RUN_ID_INVALID")
    job_id = _positive_int(expected_workflow_job_id, "CF_EVIDENCE_EXPECTED_JOB_ID_INVALID")

    require(isinstance(package, Mapping), "CF_EVIDENCE_PACKAGE_INVALID")
    require(canonical_digest(package) == package_hash, "CF_EVIDENCE_PACKAGE_HASH_MISMATCH")
    require(
        package.get("artifact")
        == "RATE_CLOUDFLARE_D1_REAL_QUALIFICATION_EVIDENCE_PACKAGE_V1"
        and package.get("status") == "EXECUTION_COMPLETED",
        "CF_EVIDENCE_PACKAGE_STATUS_INVALID",
    )

    execution = package.get("execution")
    require(isinstance(execution, Mapping), "CF_EVIDENCE_EXECUTION_MISSING")
    require(
        execution.get("workflow_run_id") == run_id
        and execution.get("workflow_job_id") == job_id
        and execution.get("workflow_attempt") == 1
        and execution.get("rerun_count") == 0,
        "CF_EVIDENCE_WORKFLOW_IDENTITY_INVALID",
    )
    require(
        execution.get("cloudflare_authorization_qualification_sha256") == auth_hash
        and execution.get("current_main_sha") == main,
        "CF_EVIDENCE_EXECUTION_TRUST_BINDING_INVALID",
    )
    require(
        execution.get("request_count") == 17
        and execution.get("admin_and_cleanup_requests") == 11
        and execution.get("runtime_requests") == 6
        and execution.get("automatic_retries") == 0
        and execution.get("redirects_followed") == 0
        and execution.get("fallback_used") is False,
        "CF_EVIDENCE_REQUEST_BUDGET_INVALID",
    )
    require(
        execution.get("admin_operations") == list(ADMIN_OPERATIONS)
        and execution.get("runtime_probes") == list(RUNTIME_PROBES)
        and execution.get("cleanup_operations") == list(CLEANUP_OPERATIONS),
        "CF_EVIDENCE_OPERATION_SEQUENCE_INVALID",
    )

    marker = package.get("consumption_marker")
    require(isinstance(marker, Mapping), "CF_EVIDENCE_MARKER_MISSING")
    require(
        marker.get("marker_execution_result_sha256") == marker_hash
        and marker.get("marker_target_sha") == main
        and isinstance(marker.get("marker_ref"), str)
        and marker["marker_ref"].startswith(
            "refs/tags/rate-v11-qualification-consumed/cloudflare-d1-"
        ),
        "CF_EVIDENCE_MARKER_BINDING_INVALID",
    )
    require(
        marker.get("marker_creation_consumed") is True
        and marker.get("readback_verified") is True
        and marker.get("create_attempts") == 1
        and marker.get("create_retries") == 0
        and marker.get("cloudflare_requests_before_marker") == 0,
        "CF_EVIDENCE_MARKER_STATE_INVALID",
    )

    expected_suffix = auth_hash[:12]
    resources = package.get("resources")
    require(isinstance(resources, Mapping), "CF_EVIDENCE_RESOURCES_MISSING")
    d1_id = str(resources.get("d1_database_id") or "").lower()
    require(bool(UUID.fullmatch(d1_id)), "CF_EVIDENCE_D1_ID_INVALID")
    require(
        resources.get("d1_database_name") == "rate-v11-qual-" + expected_suffix
        and resources.get("d1_read_replication") == "disabled",
        "CF_EVIDENCE_D1_IDENTITY_INVALID",
    )
    require(
        resources.get("worker_script_id") == "rate-v11-qual-" + expected_suffix,
        "CF_EVIDENCE_WORKER_ID_INVALID",
    )
    worker_sha = _sha64(resources.get("worker_script_sha256"), "CF_EVIDENCE_WORKER_HASH_INVALID")
    schema_sha = _sha64(resources.get("schema_sha256"), "CF_EVIDENCE_SCHEMA_HASH_INVALID")
    require(
        resources.get("worker_secret_metadata_present") is True,
        "CF_EVIDENCE_WORKER_SECRET_METADATA_MISSING",
    )
    endpoint = str(resources.get("workers_dev_endpoint") or "")
    parsed = urlparse(endpoint)
    require(
        parsed.scheme == "https"
        and parsed.hostname is not None
        and parsed.hostname.startswith(resources["worker_script_id"] + ".")
        and parsed.hostname.endswith(".workers.dev")
        and parsed.path in {"", "/"}
        and not parsed.query
        and not parsed.fragment,
        "CF_EVIDENCE_WORKERS_DEV_ENDPOINT_INVALID",
    )

    runtime = package.get("runtime_probe_results")
    require(isinstance(runtime, Mapping), "CF_EVIDENCE_RUNTIME_RESULTS_MISSING")
    require(
        set(runtime.get("statuses", {})) == set(EXPECTED_RUNTIME_STATUSES)
        and runtime.get("statuses") == EXPECTED_RUNTIME_STATUSES,
        "CF_EVIDENCE_RUNTIME_STATUS_INVALID",
    )
    require(
        runtime.get("readback_receipt_exact") is True
        and runtime.get("duplicate_overwrite_allowed") is False
        and runtime.get("post_retry_count") == 0,
        "CF_EVIDENCE_RUNTIME_SEMANTICS_INVALID",
    )

    cleanup = package.get("cleanup")
    require(isinstance(cleanup, Mapping), "CF_EVIDENCE_CLEANUP_MISSING")
    require(
        cleanup.get("worker_deleted") is True
        and cleanup.get("d1_deleted") is True
        and cleanup.get("attempts")
        == {"DELETE_WORKER_SCRIPT": 1, "DELETE_D1_DATABASE": 1}
        and cleanup.get("retry_count") == 0
        and cleanup.get("failures") == []
        and cleanup.get("residual_resources") == [],
        "CF_EVIDENCE_CLEANUP_NOT_CLOSED",
    )

    manifest = package.get("evidence_manifest")
    require(isinstance(manifest, Mapping), "CF_EVIDENCE_MANIFEST_MISSING")
    require(set(manifest) == REQUIRED_RESULT_EVIDENCE, "CF_EVIDENCE_MANIFEST_SET_INVALID")
    for name in sorted(REQUIRED_RESULT_EVIDENCE):
        item = manifest[name]
        require(
            isinstance(item, Mapping)
            and isinstance(item.get("reference"), str)
            and item["reference"].strip()
            and bool(HEX64.fullmatch(str(item.get("sha256") or "").lower())),
            "CF_EVIDENCE_MANIFEST_ITEM_INVALID:" + name,
        )
    require(
        canonical_digest(manifest) == evidence_hash
        and package.get("evidence_manifest_sha256") == evidence_hash,
        "CF_EVIDENCE_MANIFEST_HASH_MISMATCH",
    )

    require(
        package.get("secret_exposure")
        == {
            "cloudflare_api_token_in_evidence": False,
            "worker_secret_value_in_evidence": False,
        },
        "CF_EVIDENCE_SECRET_EXPOSURE_INVALID",
    )
    require(
        package.get("real_cloudflare_requests") == 17
        and package.get("provider_qualified") is False
        and package.get("production_eligible") is False
        and package.get("external_dependency_resolved") is False
        and package.get("production_credit") == 0
        and package.get("cer081_credit") == 0,
        "CF_EVIDENCE_PREMATURE_ACCEPTANCE_OR_CREDIT",
    )

    return {
        "artifact": "RATE_CLOUDFLARE_D1_REAL_QUALIFICATION_EVIDENCE_REVIEW_V1",
        "validation_status": "PASS",
        "review_disposition": "READY_FOR_CONTROL_CENTER_CLOUDFLARE_PROVIDER_ACCEPTANCE",
        "workflow_run_id": run_id,
        "workflow_job_id": job_id,
        "cloudflare_authorization_qualification_sha256": auth_hash,
        "marker_execution_result_sha256": marker_hash,
        "current_main_sha": main,
        "d1_database_id": d1_id,
        "worker_script_id": resources["worker_script_id"],
        "worker_script_sha256": worker_sha,
        "schema_sha256": schema_sha,
        "request_count": 17,
        "runtime_statuses": dict(EXPECTED_RUNTIME_STATUSES),
        "cleanup_closed": True,
        "residual_resource_count": 0,
        "provider_accepted": False,
        "provider_qualified": False,
        "production_eligible": False,
        "external_dependency_resolved": False,
        "production_credit": 0,
        "cer081_credit": 0,
    }

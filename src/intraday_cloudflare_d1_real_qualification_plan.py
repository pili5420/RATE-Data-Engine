"""Pure plan validator for one real Cloudflare Workers + D1 qualification.

This module creates no Cloudflare resource and performs no network request. It fixes
the exact temporary resource, API, probe, evidence and cleanup boundary for a later
single-use provider qualification.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping

PROVIDER = "CLOUDFLARE_WORKERS_D1"
PLAN = "WORKERS_FREE"
API_TOKEN_PERMISSIONS = {"D1 Write", "Workers Scripts Write"}
RUNTIME_PROBES = (
    "UNAUTHORIZED_GET",
    "MISSING_GET",
    "CREATE_POST",
    "READBACK_GET",
    "DUPLICATE_POST",
    "UNSUPPORTED_METHOD",
)
ADMIN_OPERATIONS = (
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
CLEANUP_OPERATIONS = (
    "DELETE_WORKER_SCRIPT",
    "DELETE_D1_DATABASE",
)
REQUIRED_EVIDENCE = {
    "WORKERS_FREE_LIMITS",
    "D1_FREE_PRICING",
    "D1_CREATE_API",
    "WORKERS_SCRIPT_UPLOAD_API",
    "WORKER_SECRETS",
    "WORKERS_DEV_ROUTING",
    "WORKERS_SUBDOMAIN_API",
    "WORKER_SCRIPT_SUBDOMAIN_API",
}


class CloudflareQualificationPlanError(RuntimeError):
    pass


def require(condition: bool, reason: str) -> None:
    if not condition:
        raise CloudflareQualificationPlanError(reason)


def validate_cloudflare_real_qualification_plan(plan: Mapping[str, Any]) -> dict[str, Any]:
    require(isinstance(plan, Mapping), "CF_QUAL_PLAN_INVALID")
    require(
        plan.get("artifact") == "RATE_CLOUDFLARE_D1_REAL_PROVIDER_QUALIFICATION_PLAN_V1",
        "CF_QUAL_PLAN_ARTIFACT_INVALID",
    )
    require(plan.get("status") == "PLAN_ONLY", "CF_QUAL_PLAN_STATUS_INVALID")
    require(plan.get("provider") == PROVIDER and plan.get("plan") == PLAN,
            "CF_QUAL_PLAN_PROVIDER_INVALID")

    evidence = plan.get("provider_evidence")
    require(isinstance(evidence, Mapping), "CF_QUAL_PLAN_EVIDENCE_MISSING")
    require(set(evidence) == REQUIRED_EVIDENCE, "CF_QUAL_PLAN_EVIDENCE_SET_INVALID")
    for key in REQUIRED_EVIDENCE:
        item = evidence[key]
        require(
            isinstance(item, Mapping)
            and isinstance(item.get("url"), str)
            and item["url"].startswith("https://")
            and isinstance(item.get("claim"), str)
            and item["claim"].strip(),
            "CF_QUAL_PLAN_EVIDENCE_INVALID:" + key,
        )

    resources = plan.get("resource_budget")
    require(isinstance(resources, Mapping), "CF_QUAL_PLAN_RESOURCE_BUDGET_MISSING")
    require(
        resources.get("create_d1_database") == 1
        and resources.get("create_worker_script") == 1
        and resources.get("create_worker_secret") == 1
        and resources.get("custom_routes") == 0
        and resources.get("custom_domains") == 0
        and resources.get("durable_objects") == 0
        and resources.get("kv_namespaces") == 0
        and resources.get("r2_buckets") == 0,
        "CF_QUAL_PLAN_RESOURCE_BUDGET_INVALID",
    )
    require(resources.get("qualification_only") is True,
            "CF_QUAL_PLAN_RESOURCE_MUST_BE_QUALIFICATION_ONLY")
    require(resources.get("persist_after_qualification") is False,
            "CF_QUAL_PLAN_RESOURCE_PERSISTENCE_FORBIDDEN")

    d1 = plan.get("d1_database")
    require(isinstance(d1, Mapping), "CF_QUAL_PLAN_D1_MISSING")
    require(
        d1.get("read_replication") == "disabled"
        and d1.get("schema_table") == "rate_execution_receipts"
        and d1.get("primary_key") == "execution_id"
        and d1.get("schema_apply_count") == 1,
        "CF_QUAL_PLAN_D1_BOUNDARY_INVALID",
    )
    require(
        d1.get("database_name_prefix") == "rate-v11-qual-receipts-"
        and d1.get("production_database_reuse_allowed") is False,
        "CF_QUAL_PLAN_D1_IDENTITY_INVALID",
    )

    worker = plan.get("worker")
    require(isinstance(worker, Mapping), "CF_QUAL_PLAN_WORKER_MISSING")
    require(
        worker.get("script_name_prefix") == "rate-v11-qual-receipts-"
        and worker.get("endpoint") == "WORKERS_DEV_ONLY"
        and worker.get("custom_route_allowed") is False
        and worker.get("custom_domain_allowed") is False,
        "CF_QUAL_PLAN_WORKER_ENDPOINT_INVALID",
    )
    require(
        worker.get("secret_name") == "RATE_D1_RECEIPT_WORKER_TOKEN"
        and worker.get("secret_value_embedded") is False
        and worker.get("d1_binding") == "DB",
        "CF_QUAL_PLAN_WORKER_BINDING_INVALID",
    )

    admin = plan.get("cloudflare_admin_credential")
    require(isinstance(admin, Mapping), "CF_QUAL_PLAN_ADMIN_CREDENTIAL_MISSING")
    require(
        admin.get("store") == "GITHUB_ACTIONS_SECRET"
        and admin.get("secret_name") == "CLOUDFLARE_API_TOKEN"
        and admin.get("account_id_source") == "GITHUB_ACTIONS_VARIABLE"
        and admin.get("account_id_name") == "CLOUDFLARE_ACCOUNT_ID"
        and admin.get("secret_value_embedded") is False,
        "CF_QUAL_PLAN_ADMIN_CREDENTIAL_BOUNDARY_INVALID",
    )
    require(
        set(admin.get("required_api_token_permissions", [])) == API_TOKEN_PERMISSIONS,
        "CF_QUAL_PLAN_API_TOKEN_PERMISSIONS_INVALID",
    )
    require(
        set(admin.get("forbidden_api_token_permissions", []))
        >= {"Zone DNS Write", "Account Settings Write"},
        "CF_QUAL_PLAN_API_TOKEN_SCOPE_NOT_NARROW",
    )

    admin_ops = plan.get("admin_operation_budget")
    require(
        isinstance(admin_ops, Mapping)
        and set(admin_ops) == set(ADMIN_OPERATIONS)
        and all(admin_ops[name] == 1 for name in ADMIN_OPERATIONS),
        "CF_QUAL_PLAN_ADMIN_OPERATION_BUDGET_INVALID",
    )

    probes = plan.get("runtime_probe_budget")
    require(
        isinstance(probes, Mapping)
        and set(probes) == set(RUNTIME_PROBES)
        and all(probes[name] == 1 for name in RUNTIME_PROBES),
        "CF_QUAL_PLAN_RUNTIME_PROBE_BUDGET_INVALID",
    )
    require(plan.get("automatic_retry_allowed") is False,
            "CF_QUAL_PLAN_AUTORETRY_FORBIDDEN")
    require(plan.get("fallback_allowed") is False,
            "CF_QUAL_PLAN_FALLBACK_FORBIDDEN")

    expected = plan.get("runtime_acceptance")
    require(isinstance(expected, Mapping), "CF_QUAL_PLAN_RUNTIME_ACCEPTANCE_MISSING")
    require(
        expected.get("unauthorized_status") == 401
        and expected.get("missing_status") == 404
        and expected.get("create_status") == 201
        and expected.get("readback_status") == 200
        and expected.get("duplicate_status") == 409
        and expected.get("unsupported_method_status") == 405,
        "CF_QUAL_PLAN_RUNTIME_STATUS_INVALID",
    )
    require(
        expected.get("readback_receipt_exact") is True
        and expected.get("duplicate_overwrite_allowed") is False
        and expected.get("post_retry_count") == 0,
        "CF_QUAL_PLAN_RUNTIME_SEMANTICS_INVALID",
    )

    cleanup = plan.get("cleanup")
    require(isinstance(cleanup, Mapping), "CF_QUAL_PLAN_CLEANUP_MISSING")
    require(
        cleanup.get("mandatory") is True
        and cleanup.get("cleanup_even_on_failure") is True
        and cleanup.get("qualification_credit_requires_cleanup_success") is True,
        "CF_QUAL_PLAN_CLEANUP_POLICY_INVALID",
    )
    cleanup_ops = cleanup.get("operation_budget")
    require(
        isinstance(cleanup_ops, Mapping)
        and set(cleanup_ops) == set(CLEANUP_OPERATIONS)
        and all(cleanup_ops[name] == 1 for name in CLEANUP_OPERATIONS),
        "CF_QUAL_PLAN_CLEANUP_BUDGET_INVALID",
    )
    require(
        cleanup.get("cleanup_retry_allowed") is False
        and cleanup.get("residual_resource_disposition") == "BLOCKED_RESIDUAL_RESOURCE",
        "CF_QUAL_PLAN_CLEANUP_FAIL_CLOSED_INVALID",
    )

    evidence_out = plan.get("required_result_evidence")
    require(
        isinstance(evidence_out, list)
        and set(evidence_out) == {
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
        },
        "CF_QUAL_PLAN_RESULT_EVIDENCE_INVALID",
    )

    require(
        plan.get("real_cloudflare_requests") == 0
        and plan.get("credentials_read") == 0
        and plan.get("resources_created") == 0
        and plan.get("qualification_executed") is False
        and plan.get("provider_qualified") is False
        and plan.get("production_eligible") is False
        and plan.get("external_dependency_resolved") is False
        and plan.get("production_credit") == 0
        and plan.get("cer081_credit") == 0,
        "CF_QUAL_PLAN_PREMATURE_EXECUTION_OR_CREDIT",
    )

    return {
        "artifact": "RATE_CLOUDFLARE_D1_REAL_PROVIDER_QUALIFICATION_PLAN_REVIEW_V1",
        "validation_status": "PASS",
        "provider": PROVIDER,
        "plan": PLAN,
        "qualification_scope": "TEMPORARY_RESOURCES_ONLY",
        "resource_budget": deepcopy(dict(resources)),
        "admin_operation_budget": deepcopy(dict(admin_ops)),
        "runtime_probe_budget": deepcopy(dict(probes)),
        "cleanup_operation_budget": deepcopy(dict(cleanup_ops)),
        "api_token_permissions": sorted(API_TOKEN_PERMISSIONS),
        "workers_endpoint": "WORKERS_DEV_ONLY",
        "d1_read_replication": "disabled",
        "automatic_retry_allowed": False,
        "fallback_allowed": False,
        "qualification_executed": False,
        "provider_qualified": False,
        "real_cloudflare_requests": 0,
        "credentials_read": 0,
        "resources_created": 0,
        "production_credit": 0,
        "cer081_credit": 0,
        "next_gate": "EXPLICIT_CLOUDFLARE_REAL_QUALIFICATION_AUTHORIZATION",
    }

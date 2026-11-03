"""Offline qualification for the Cloudflare Workers + D1 authority-store candidate.

This selects a provider architecture for later real qualification. It performs no
Cloudflare request, creates no Worker/database, and reads no credential.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping

PROVIDER = "CLOUDFLARE_WORKERS_D1"
PLAN = "WORKERS_FREE"
TABLE = "rate_execution_receipts"
ROUTE_TEMPLATE = "/v1/execution-receipts/{execution_id}"
REQUIRED_EVIDENCE = {
    "WORKERS_FREE_LIMITS",
    "D1_FREE_PRICING",
    "D1_PRIMARY_READ_SEMANTICS",
    "D1_READ_REPLICATION_CONTROL",
    "D1_SQLITE_SEMANTICS",
}
AMBIGUOUS_POLICY = "READ_SAME_EXECUTION_ID_DO_NOT_RETRY_CREATE"


class D1CandidateError(RuntimeError):
    pass


def require(condition: bool, reason: str) -> None:
    if not condition:
        raise D1CandidateError(reason)


def validate_cloudflare_d1_candidate(candidate: Mapping[str, Any]) -> dict[str, Any]:
    require(isinstance(candidate, Mapping), "D1_CANDIDATE_INVALID")
    require(
        candidate.get("artifact")
        == "RATE_INTRADAY_CLOUDFLARE_D1_AUTHORITY_STORE_CANDIDATE_V1",
        "D1_CANDIDATE_ARTIFACT_INVALID",
    )
    require(candidate.get("provider") == PROVIDER, "D1_CANDIDATE_PROVIDER_INVALID")
    require(candidate.get("plan") == PLAN, "D1_CANDIDATE_PLAN_INVALID")

    evidence = candidate.get("provider_evidence")
    require(isinstance(evidence, Mapping), "D1_CANDIDATE_EVIDENCE_MISSING")
    require(set(evidence) == REQUIRED_EVIDENCE, "D1_CANDIDATE_EVIDENCE_SET_INVALID")
    for key in REQUIRED_EVIDENCE:
        item = evidence[key]
        require(
            isinstance(item, Mapping)
            and isinstance(item.get("url"), str)
            and item["url"].startswith("https://")
            and isinstance(item.get("claim"), str)
            and item["claim"].strip(),
            "D1_CANDIDATE_EVIDENCE_INVALID:" + key,
        )

    worker = candidate.get("worker_proxy")
    require(isinstance(worker, Mapping), "D1_CANDIDATE_WORKER_PROXY_MISSING")
    require(
        worker.get("transport") == "HTTPS_TLS"
        and worker.get("server_identity_verified") is True
        and worker.get("fail_mode") == "FAIL_CLOSED",
        "D1_CANDIDATE_WORKER_TRANSPORT_INVALID",
    )
    require(
        worker.get("route_template") == ROUTE_TEMPLATE,
        "D1_CANDIDATE_WORKER_ROUTE_INVALID",
    )
    require(
        worker.get("allowed_methods") == ["GET", "POST"],
        "D1_CANDIDATE_WORKER_METHODS_INVALID",
    )
    require(
        worker.get("arbitrary_sql_exposed") is False
        and worker.get("update_route_exposed") is False
        and worker.get("delete_route_exposed") is False
        and worker.get("list_route_exposed") is False,
        "D1_CANDIDATE_WORKER_SURFACE_TOO_BROAD",
    )
    require(
        worker.get("max_create_requests_per_execution") == 1,
        "D1_CANDIDATE_CREATE_BUDGET_INVALID",
    )
    require(
        worker.get("ambiguous_create_policy") == AMBIGUOUS_POLICY,
        "D1_CANDIDATE_AMBIGUOUS_POLICY_INVALID",
    )

    auth = worker.get("authentication")
    require(isinstance(auth, Mapping), "D1_CANDIDATE_AUTH_MISSING")
    require(
        auth.get("scheme") == "BEARER_SHARED_SECRET"
        and auth.get("github_secret_name") == "RATE_D1_RECEIPT_WORKER_TOKEN"
        and auth.get("worker_secret_name") == "RATE_D1_RECEIPT_WORKER_TOKEN"
        and auth.get("secret_value_embedded") is False,
        "D1_CANDIDATE_AUTH_BOUNDARY_INVALID",
    )

    database = candidate.get("d1")
    require(isinstance(database, Mapping), "D1_CANDIDATE_DATABASE_MISSING")
    require(
        database.get("access_path") == "WORKER_BINDING_ONLY"
        and database.get("public_admin_rest_exposed_to_executor") is False,
        "D1_CANDIDATE_DATABASE_ACCESS_INVALID",
    )
    require(
        database.get("read_replication") == "DISABLED",
        "D1_CANDIDATE_READ_REPLICATION_MUST_BE_DISABLED",
    )
    require(
        database.get("query_consistency") == "PRIMARY_READ_AFTER_WRITE",
        "D1_CANDIDATE_CONSISTENCY_INVALID",
    )
    require(
        database.get("engine_semantics") == "SQLITE",
        "D1_CANDIDATE_ENGINE_INVALID",
    )

    schema = database.get("schema")
    require(isinstance(schema, Mapping), "D1_CANDIDATE_SCHEMA_MISSING")
    require(schema.get("table") == TABLE, "D1_CANDIDATE_TABLE_INVALID")
    require(schema.get("primary_key") == "execution_id", "D1_CANDIDATE_PRIMARY_KEY_INVALID")
    require(
        schema.get("receipt_json_not_null") is True
        and schema.get("receipt_sha256_not_null") is True
        and schema.get("created_at_not_null") is True,
        "D1_CANDIDATE_SCHEMA_NULLABILITY_INVALID",
    )
    require(
        schema.get("create_semantics") == "PLAIN_INSERT_PRIMARY_KEY_CONFLICT_FAIL"
        and schema.get("overwrite_semantics") == "FORBIDDEN"
        and schema.get("delete_semantics") == "FORBIDDEN",
        "D1_CANDIDATE_WRITE_SEMANTICS_INVALID",
    )

    immutability = database.get("immutability")
    require(isinstance(immutability, Mapping), "D1_CANDIDATE_IMMUTABILITY_MISSING")
    require(
        immutability.get("worker_update_code_path") is False
        and immutability.get("worker_delete_code_path") is False
        and immutability.get("schema_update_guard_required") is True
        and immutability.get("schema_delete_guard_required") is True,
        "D1_CANDIDATE_IMMUTABILITY_INVALID",
    )

    quota = candidate.get("free_plan_capacity")
    require(isinstance(quota, Mapping), "D1_CANDIDATE_FREE_CAPACITY_MISSING")
    require(
        isinstance(quota.get("worker_requests_per_day"), int)
        and quota["worker_requests_per_day"] >= 1000
        and isinstance(quota.get("d1_rows_read_per_day"), int)
        and quota["d1_rows_read_per_day"] >= 1000
        and isinstance(quota.get("d1_rows_written_per_day"), int)
        and quota["d1_rows_written_per_day"] >= 100,
        "D1_CANDIDATE_FREE_CAPACITY_INSUFFICIENT",
    )
    require(
        quota.get("rate_use_expected_receipt_writes_per_day") <= 4
        and quota.get("rate_use_expected_receipt_reads_per_day") <= 20,
        "D1_CANDIDATE_RATE_USAGE_BUDGET_INVALID",
    )

    require(
        candidate.get("real_provider_requests") == 0
        and candidate.get("credentials_read") == 0
        and candidate.get("resources_created") == 0
        and candidate.get("provider_qualified") is False
        and candidate.get("production_eligible") is False
        and candidate.get("external_dependency_resolved") is False
        and candidate.get("production_credit") == 0
        and candidate.get("cer081_credit") == 0,
        "D1_CANDIDATE_PREMATURE_CREDIT_OR_EXECUTION",
    )

    return {
        "artifact": "RATE_INTRADAY_REAL_AUTHORITY_STORE_PROVIDER_CANDIDATE_QUALIFICATION_V1",
        "validation_status": "PASS",
        "provider": PROVIDER,
        "plan": PLAN,
        "architecture": "AUTHENTICATED_WORKER_PROXY_PLUS_D1",
        "route_template": ROUTE_TEMPLATE,
        "table": TABLE,
        "read_replication": "DISABLED",
        "atomic_create_if_absent": True,
        "strong_read_after_write": True,
        "overwrite_allowed": False,
        "delete_allowed": False,
        "ambiguous_create_policy": AMBIGUOUS_POLICY,
        "credential_secret_name": "RATE_D1_RECEIPT_WORKER_TOKEN",
        "provider_selected_for_live_qualification": True,
        "provider_qualified": False,
        "real_provider_requests": 0,
        "credentials_read": 0,
        "resources_created": 0,
        "production_eligible": False,
        "external_dependency_resolved": False,
        "production_credit": 0,
        "cer081_credit": 0,
        "next_gate": "CLOUDFLARE_D1_REAL_PROVIDER_QUALIFICATION",
    }

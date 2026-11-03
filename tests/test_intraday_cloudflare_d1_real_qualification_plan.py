"""Tests for one-shot Cloudflare real-provider qualification planning."""
from __future__ import annotations

from copy import deepcopy
import unittest

from src.intraday_cloudflare_d1_real_qualification_plan import (
    CloudflareQualificationPlanError,
    REQUIRED_EVIDENCE,
    validate_cloudflare_real_qualification_plan,
)


def plan():
    evidence_urls = {
        "WORKERS_FREE_LIMITS": "https://developers.cloudflare.com/workers/platform/limits/",
        "D1_FREE_PRICING": "https://developers.cloudflare.com/d1/platform/pricing/",
        "D1_CREATE_API": "https://developers.cloudflare.com/api/resources/d1/subresources/database/methods/create/",
        "WORKERS_SCRIPT_UPLOAD_API": "https://developers.cloudflare.com/api/resources/workers/subresources/scripts/methods/update/",
        "WORKER_SECRETS": "https://developers.cloudflare.com/workers/configuration/secrets/",
        "WORKERS_DEV_ROUTING": "https://developers.cloudflare.com/workers/configuration/routing/",
        "WORKERS_SUBDOMAIN_API": "https://developers.cloudflare.com/api/resources/workers/subresources/subdomains/methods/get/",
        "WORKER_SCRIPT_SUBDOMAIN_API": "https://developers.cloudflare.com/api/resources/workers/subresources/scripts/subresources/subdomain/methods/get/",
    }
    return {
        "artifact": "RATE_CLOUDFLARE_D1_REAL_PROVIDER_QUALIFICATION_PLAN_V1",
        "status": "PLAN_ONLY",
        "provider": "CLOUDFLARE_WORKERS_D1",
        "plan": "WORKERS_FREE",
        "provider_evidence": {
            key: {"url": evidence_urls[key], "claim": key}
            for key in REQUIRED_EVIDENCE
        },
        "resource_budget": {
            "create_d1_database": 1,
            "create_worker_script": 1,
            "create_worker_secret": 1,
            "custom_routes": 0,
            "custom_domains": 0,
            "durable_objects": 0,
            "kv_namespaces": 0,
            "r2_buckets": 0,
            "qualification_only": True,
            "persist_after_qualification": False,
        },
        "d1_database": {
            "read_replication": "disabled",
            "schema_table": "rate_execution_receipts",
            "primary_key": "execution_id",
            "schema_apply_count": 1,
            "database_name_prefix": "rate-v11-qual-receipts-",
            "production_database_reuse_allowed": False,
        },
        "worker": {
            "script_name_prefix": "rate-v11-qual-receipts-",
            "endpoint": "WORKERS_DEV_ONLY",
            "custom_route_allowed": False,
            "custom_domain_allowed": False,
            "secret_name": "RATE_D1_RECEIPT_WORKER_TOKEN",
            "secret_value_embedded": False,
            "d1_binding": "DB",
        },
        "cloudflare_admin_credential": {
            "store": "GITHUB_ACTIONS_SECRET",
            "secret_name": "CLOUDFLARE_API_TOKEN",
            "account_id_source": "GITHUB_ACTIONS_VARIABLE",
            "account_id_name": "CLOUDFLARE_ACCOUNT_ID",
            "secret_value_embedded": False,
            "required_api_token_permissions": ["D1 Write", "Workers Scripts Write"],
            "forbidden_api_token_permissions": ["Zone DNS Write", "Account Settings Write"],
        },
        "admin_operation_budget": {
            "CREATE_D1_DATABASE": 1,
            "UPLOAD_WORKER_MODULE": 1,
            "PUT_WORKER_SECRET": 1,
            "APPLY_D1_SCHEMA": 1,
            "GET_D1_METADATA": 1,
            "GET_WORKER_SCRIPT": 1,
            "GET_WORKER_SECRET_METADATA": 1,
            "GET_WORKERS_SUBDOMAIN": 1,
            "GET_WORKER_SCRIPT_SUBDOMAIN": 1,
        },
        "runtime_probe_budget": {
            "UNAUTHORIZED_GET": 1,
            "MISSING_GET": 1,
            "CREATE_POST": 1,
            "READBACK_GET": 1,
            "DUPLICATE_POST": 1,
            "UNSUPPORTED_METHOD": 1,
        },
        "runtime_acceptance": {
            "unauthorized_status": 401,
            "missing_status": 404,
            "create_status": 201,
            "readback_status": 200,
            "duplicate_status": 409,
            "unsupported_method_status": 405,
            "readback_receipt_exact": True,
            "duplicate_overwrite_allowed": False,
            "post_retry_count": 0,
        },
        "automatic_retry_allowed": False,
        "fallback_allowed": False,
        "cleanup": {
            "mandatory": True,
            "cleanup_even_on_failure": True,
            "qualification_credit_requires_cleanup_success": True,
            "operation_budget": {
                "DELETE_WORKER_SCRIPT": 1,
                "DELETE_D1_DATABASE": 1,
            },
            "cleanup_retry_allowed": False,
            "residual_resource_disposition": "BLOCKED_RESIDUAL_RESOURCE",
        },
        "required_result_evidence": [
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
        ],
        "real_cloudflare_requests": 0,
        "credentials_read": 0,
        "resources_created": 0,
        "qualification_executed": False,
        "provider_qualified": False,
        "production_eligible": False,
        "external_dependency_resolved": False,
        "production_credit": 0,
        "cer081_credit": 0,
    }


class CloudflareQualificationPlanTests(unittest.TestCase):
    def qualify(self, value=None):
        return validate_cloudflare_real_qualification_plan(value or plan())

    def test_exact_plan_passes_without_cloudflare_execution(self):
        result = self.qualify()
        self.assertEqual(result["validation_status"], "PASS")
        self.assertEqual(result["qualification_scope"], "TEMPORARY_RESOURCES_ONLY")
        self.assertFalse(result["qualification_executed"])
        self.assertFalse(result["provider_qualified"])
        self.assertEqual(result["real_cloudflare_requests"], 0)

    def test_resource_budget_is_exact_and_qualification_only(self):
        value = plan()
        value["resource_budget"]["custom_routes"] = 1
        with self.assertRaisesRegex(CloudflareQualificationPlanError, "RESOURCE_BUDGET_INVALID"):
            self.qualify(value)
        value = plan()
        value["resource_budget"]["persist_after_qualification"] = True
        with self.assertRaisesRegex(CloudflareQualificationPlanError, "PERSISTENCE_FORBIDDEN"):
            self.qualify(value)

    def test_d1_replication_and_identity_are_exact(self):
        value = plan()
        value["d1_database"]["read_replication"] = "auto"
        with self.assertRaisesRegex(CloudflareQualificationPlanError, "D1_BOUNDARY_INVALID"):
            self.qualify(value)
        value = plan()
        value["d1_database"]["production_database_reuse_allowed"] = True
        with self.assertRaisesRegex(CloudflareQualificationPlanError, "D1_IDENTITY_INVALID"):
            self.qualify(value)

    def test_worker_endpoint_is_workers_dev_only_with_no_routes(self):
        value = plan()
        value["worker"]["endpoint"] = "CUSTOM_DOMAIN"
        with self.assertRaisesRegex(CloudflareQualificationPlanError, "WORKER_ENDPOINT_INVALID"):
            self.qualify(value)
        value = plan()
        value["worker"]["custom_route_allowed"] = True
        with self.assertRaisesRegex(CloudflareQualificationPlanError, "WORKER_ENDPOINT_INVALID"):
            self.qualify(value)

    def test_api_token_scope_is_minimal(self):
        value = plan()
        value["cloudflare_admin_credential"]["required_api_token_permissions"].append("Zone DNS Write")
        with self.assertRaisesRegex(CloudflareQualificationPlanError, "API_TOKEN_PERMISSIONS_INVALID"):
            self.qualify(value)
        value = plan()
        value["cloudflare_admin_credential"]["secret_value_embedded"] = True
        with self.assertRaisesRegex(CloudflareQualificationPlanError, "ADMIN_CREDENTIAL_BOUNDARY_INVALID"):
            self.qualify(value)

    def test_admin_and_runtime_budgets_are_exact(self):
        value = plan()
        value["admin_operation_budget"]["CREATE_D1_DATABASE"] = 2
        with self.assertRaisesRegex(CloudflareQualificationPlanError, "ADMIN_OPERATION_BUDGET_INVALID"):
            self.qualify(value)
        value = plan()
        value["runtime_probe_budget"]["CREATE_POST"] = 2
        with self.assertRaisesRegex(CloudflareQualificationPlanError, "RUNTIME_PROBE_BUDGET_INVALID"):
            self.qualify(value)

    def test_runtime_status_contract_is_exact(self):
        value = plan()
        value["runtime_acceptance"]["duplicate_status"] = 200
        with self.assertRaisesRegex(CloudflareQualificationPlanError, "RUNTIME_STATUS_INVALID"):
            self.qualify(value)
        value = plan()
        value["runtime_acceptance"]["post_retry_count"] = 1
        with self.assertRaisesRegex(CloudflareQualificationPlanError, "RUNTIME_SEMANTICS_INVALID"):
            self.qualify(value)

    def test_cleanup_is_mandatory_for_qualification_credit(self):
        value = plan()
        value["cleanup"]["mandatory"] = False
        with self.assertRaisesRegex(CloudflareQualificationPlanError, "CLEANUP_POLICY_INVALID"):
            self.qualify(value)
        value = plan()
        value["cleanup"]["operation_budget"]["DELETE_D1_DATABASE"] = 0
        with self.assertRaisesRegex(CloudflareQualificationPlanError, "CLEANUP_BUDGET_INVALID"):
            self.qualify(value)
        value = plan()
        value["cleanup"]["cleanup_retry_allowed"] = True
        with self.assertRaisesRegex(CloudflareQualificationPlanError, "CLEANUP_FAIL_CLOSED_INVALID"):
            self.qualify(value)

    def test_provider_evidence_set_is_exact(self):
        value = plan()
        value["provider_evidence"].pop(next(iter(REQUIRED_EVIDENCE)))
        with self.assertRaisesRegex(CloudflareQualificationPlanError, "EVIDENCE_SET_INVALID"):
            self.qualify(value)

    def test_plan_cannot_claim_execution_or_credit(self):
        for field, bad in (
            ("real_cloudflare_requests", 1),
            ("credentials_read", 1),
            ("resources_created", 1),
            ("qualification_executed", True),
            ("provider_qualified", True),
            ("production_eligible", True),
            ("external_dependency_resolved", True),
            ("production_credit", 1),
            ("cer081_credit", 1),
        ):
            value = plan()
            value[field] = bad
            with self.subTest(field=field), self.assertRaisesRegex(
                CloudflareQualificationPlanError, "PREMATURE_EXECUTION_OR_CREDIT"
            ):
                self.qualify(value)


if __name__ == "__main__":
    unittest.main()

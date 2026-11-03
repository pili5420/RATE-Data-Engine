"""Tests for Cloudflare Workers + D1 authority-store candidate qualification."""
from __future__ import annotations

from copy import deepcopy
import unittest

from src.intraday_cloudflare_d1_authority_store_candidate import (
    D1CandidateError,
    REQUIRED_EVIDENCE,
    validate_cloudflare_d1_candidate,
)


def candidate():
    evidence_urls = {
        "WORKERS_FREE_LIMITS": "https://developers.cloudflare.com/workers/platform/limits/",
        "D1_FREE_PRICING": "https://developers.cloudflare.com/d1/platform/pricing/",
        "D1_PRIMARY_READ_SEMANTICS": "https://developers.cloudflare.com/d1/best-practices/read-replication/",
        "D1_READ_REPLICATION_CONTROL": "https://developers.cloudflare.com/api/resources/d1/subresources/database/methods/create/",
        "D1_SQLITE_SEMANTICS": "https://developers.cloudflare.com/d1/best-practices/query-d1/",
    }
    return {
        "artifact": "RATE_INTRADAY_CLOUDFLARE_D1_AUTHORITY_STORE_CANDIDATE_V1",
        "provider": "CLOUDFLARE_WORKERS_D1",
        "plan": "WORKERS_FREE",
        "provider_evidence": {
            key: {"url": evidence_urls[key], "claim": key}
            for key in REQUIRED_EVIDENCE
        },
        "worker_proxy": {
            "transport": "HTTPS_TLS",
            "server_identity_verified": True,
            "fail_mode": "FAIL_CLOSED",
            "route_template": "/v1/execution-receipts/{execution_id}",
            "allowed_methods": ["GET", "POST"],
            "arbitrary_sql_exposed": False,
            "update_route_exposed": False,
            "delete_route_exposed": False,
            "list_route_exposed": False,
            "max_create_requests_per_execution": 1,
            "ambiguous_create_policy": "READ_SAME_EXECUTION_ID_DO_NOT_RETRY_CREATE",
            "authentication": {
                "scheme": "BEARER_SHARED_SECRET",
                "github_secret_name": "RATE_D1_RECEIPT_WORKER_TOKEN",
                "worker_secret_name": "RATE_D1_RECEIPT_WORKER_TOKEN",
                "secret_value_embedded": False,
            },
        },
        "d1": {
            "access_path": "WORKER_BINDING_ONLY",
            "public_admin_rest_exposed_to_executor": False,
            "read_replication": "DISABLED",
            "query_consistency": "PRIMARY_READ_AFTER_WRITE",
            "engine_semantics": "SQLITE",
            "schema": {
                "table": "rate_execution_receipts",
                "primary_key": "execution_id",
                "receipt_json_not_null": True,
                "receipt_sha256_not_null": True,
                "created_at_not_null": True,
                "create_semantics": "PLAIN_INSERT_PRIMARY_KEY_CONFLICT_FAIL",
                "overwrite_semantics": "FORBIDDEN",
                "delete_semantics": "FORBIDDEN",
            },
            "immutability": {
                "worker_update_code_path": False,
                "worker_delete_code_path": False,
                "schema_update_guard_required": True,
                "schema_delete_guard_required": True,
            },
        },
        "free_plan_capacity": {
            "worker_requests_per_day": 100000,
            "d1_rows_read_per_day": 5000000,
            "d1_rows_written_per_day": 100000,
            "rate_use_expected_receipt_writes_per_day": 1,
            "rate_use_expected_receipt_reads_per_day": 4,
        },
        "real_provider_requests": 0,
        "credentials_read": 0,
        "resources_created": 0,
        "provider_qualified": False,
        "production_eligible": False,
        "external_dependency_resolved": False,
        "production_credit": 0,
        "cer081_credit": 0,
    }


class D1CandidateTests(unittest.TestCase):
    def qualify(self, value=None):
        return validate_cloudflare_d1_candidate(value or candidate())

    def test_exact_worker_d1_candidate_passes_design_only(self):
        result = self.qualify()
        self.assertEqual(result["validation_status"], "PASS")
        self.assertEqual(result["provider"], "CLOUDFLARE_WORKERS_D1")
        self.assertEqual(result["plan"], "WORKERS_FREE")
        self.assertTrue(result["provider_selected_for_live_qualification"])
        self.assertFalse(result["provider_qualified"])
        self.assertEqual(result["real_provider_requests"], 0)
        self.assertEqual(result["resources_created"], 0)

    def test_executor_must_not_receive_d1_admin_rest_access(self):
        value = candidate()
        value["d1"]["access_path"] = "PUBLIC_D1_REST"
        value["d1"]["public_admin_rest_exposed_to_executor"] = True
        with self.assertRaisesRegex(D1CandidateError, "DATABASE_ACCESS_INVALID"):
            self.qualify(value)

    def test_read_replication_must_be_disabled_for_simple_primary_readback(self):
        value = candidate()
        value["d1"]["read_replication"] = "AUTO"
        with self.assertRaisesRegex(D1CandidateError, "READ_REPLICATION_MUST_BE_DISABLED"):
            self.qualify(value)

    def test_execution_id_must_be_database_primary_key(self):
        value = candidate()
        value["d1"]["schema"]["primary_key"] = "id"
        with self.assertRaisesRegex(D1CandidateError, "PRIMARY_KEY_INVALID"):
            self.qualify(value)

    def test_worker_surface_is_create_read_only(self):
        for field in (
            "arbitrary_sql_exposed",
            "update_route_exposed",
            "delete_route_exposed",
            "list_route_exposed",
        ):
            value = candidate()
            value["worker_proxy"][field] = True
            with self.subTest(field=field), self.assertRaisesRegex(
                D1CandidateError, "SURFACE_TOO_BROAD"
            ):
                self.qualify(value)

    def test_ambiguous_create_must_readback_not_retry(self):
        value = candidate()
        value["worker_proxy"]["ambiguous_create_policy"] = "RETRY_CREATE"
        with self.assertRaisesRegex(D1CandidateError, "AMBIGUOUS_POLICY_INVALID"):
            self.qualify(value)

    def test_single_create_request_budget_is_exact(self):
        value = candidate()
        value["worker_proxy"]["max_create_requests_per_execution"] = 2
        with self.assertRaisesRegex(D1CandidateError, "CREATE_BUDGET_INVALID"):
            self.qualify(value)

    def test_secret_value_and_secret_name_boundaries(self):
        value = candidate()
        value["worker_proxy"]["authentication"]["secret_value_embedded"] = True
        with self.assertRaisesRegex(D1CandidateError, "AUTH_BOUNDARY_INVALID"):
            self.qualify(value)
        value = candidate()
        value["worker_proxy"]["authentication"]["github_secret_name"] = "OTHER"
        with self.assertRaisesRegex(D1CandidateError, "AUTH_BOUNDARY_INVALID"):
            self.qualify(value)

    def test_schema_must_forbid_overwrite_and_delete(self):
        for field, bad in (
            ("create_semantics", "UPSERT"),
            ("overwrite_semantics", "ALLOWED"),
            ("delete_semantics", "ALLOWED"),
        ):
            value = candidate()
            value["d1"]["schema"][field] = bad
            with self.subTest(field=field), self.assertRaisesRegex(
                D1CandidateError, "WRITE_SEMANTICS_INVALID"
            ):
                self.qualify(value)

    def test_schema_guards_and_worker_paths_are_required(self):
        for field, bad in (
            ("worker_update_code_path", True),
            ("worker_delete_code_path", True),
            ("schema_update_guard_required", False),
            ("schema_delete_guard_required", False),
        ):
            value = candidate()
            value["d1"]["immutability"][field] = bad
            with self.subTest(field=field), self.assertRaisesRegex(
                D1CandidateError, "IMMUTABILITY_INVALID"
            ):
                self.qualify(value)

    def test_free_capacity_must_remain_far_above_rate_usage(self):
        value = candidate()
        value["free_plan_capacity"]["d1_rows_written_per_day"] = 10
        with self.assertRaisesRegex(D1CandidateError, "FREE_CAPACITY_INSUFFICIENT"):
            self.qualify(value)
        value = candidate()
        value["free_plan_capacity"]["rate_use_expected_receipt_writes_per_day"] = 5
        with self.assertRaisesRegex(D1CandidateError, "RATE_USAGE_BUDGET_INVALID"):
            self.qualify(value)

    def test_provider_evidence_set_is_exact(self):
        value = candidate()
        value["provider_evidence"].pop(next(iter(REQUIRED_EVIDENCE)))
        with self.assertRaisesRegex(D1CandidateError, "EVIDENCE_SET_INVALID"):
            self.qualify(value)

    def test_design_gate_cannot_claim_provider_or_production_credit(self):
        for field, bad in (
            ("real_provider_requests", 1),
            ("credentials_read", 1),
            ("resources_created", 1),
            ("provider_qualified", True),
            ("production_eligible", True),
            ("external_dependency_resolved", True),
            ("production_credit", 1),
            ("cer081_credit", 1),
        ):
            value = candidate()
            value[field] = bad
            with self.subTest(field=field), self.assertRaisesRegex(
                D1CandidateError, "PREMATURE_CREDIT_OR_EXECUTION"
            ):
                self.qualify(value)


if __name__ == "__main__":
    unittest.main()

"""Tests for explicit one-shot Cloudflare real qualification authorization."""
from __future__ import annotations

import unittest

from src.intraday_activation_candidate_review import canonical_digest
from src.intraday_cloudflare_d1_real_qualification_authorization import (
    CloudflareQualificationAuthorizationError,
    EXPECTED_ADMIN_BUDGET,
    EXPECTED_CLEANUP_BUDGET,
    EXPECTED_RESOURCE_BUDGET,
    EXPECTED_RUNTIME_BUDGET,
    validate_cloudflare_real_qualification_authorization,
)

MAIN = "1" * 40
SCAFFOLD = "2" * 64
NODE = "3" * 64
DECISION = "CC-CF-D1-QUAL-2026-11-04"


def plan_review():
    return {
        "artifact": "RATE_CLOUDFLARE_D1_REAL_PROVIDER_QUALIFICATION_PLAN_REVIEW_V1",
        "validation_status": "PASS",
        "provider": "CLOUDFLARE_WORKERS_D1",
        "plan": "WORKERS_FREE",
        "qualification_scope": "TEMPORARY_RESOURCES_ONLY",
        "resource_budget": dict(EXPECTED_RESOURCE_BUDGET),
        "admin_operation_budget": dict(EXPECTED_ADMIN_BUDGET),
        "runtime_probe_budget": dict(EXPECTED_RUNTIME_BUDGET),
        "cleanup_operation_budget": dict(EXPECTED_CLEANUP_BUDGET),
        "api_token_permissions": ["D1 Write", "Workers Scripts Write"],
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


def authorization(plan_hash):
    return {
        "artifact": "RATE_CLOUDFLARE_D1_REAL_PROVIDER_QUALIFICATION_AUTHORIZATION_V1",
        "status": "CLOUDFLARE_REAL_QUALIFICATION_AUTHORIZED",
        "control_center_decision_id": DECISION,
        "current_main_sha": MAIN,
        "plan_review_sha256": plan_hash,
        "scaffold_sha256": SCAFFOLD,
        "node_review_sha256": NODE,
        "provider": "CLOUDFLARE_WORKERS_D1",
        "plan": "WORKERS_FREE",
        "single_use": True,
        "execution_consumed": False,
        "automatic_retry_allowed": False,
        "fallback_allowed": False,
        "resource_budget": dict(EXPECTED_RESOURCE_BUDGET),
        "admin_operation_budget": dict(EXPECTED_ADMIN_BUDGET),
        "runtime_probe_budget": dict(EXPECTED_RUNTIME_BUDGET),
        "cleanup_operation_budget": dict(EXPECTED_CLEANUP_BUDGET),
        "api_token_secret_name": "CLOUDFLARE_API_TOKEN",
        "account_id_variable_name": "CLOUDFLARE_ACCOUNT_ID",
        "worker_secret_name": "RATE_D1_RECEIPT_WORKER_TOKEN",
        "credential_value_embedded": False,
        "d1_read_replication": "disabled",
        "workers_endpoint": "WORKERS_DEV_ONLY",
        "cleanup_required": True,
        "qualification_credit_requires_cleanup_success": True,
        "residual_resource_disposition": "BLOCKED_RESIDUAL_RESOURCE",
        "qualification_execution_performed": False,
        "real_cloudflare_requests": 0,
        "credentials_read": 0,
        "resources_created": 0,
        "provider_qualified": False,
        "production_credit": 0,
        "cer081_credit": 0,
    }


class CloudflareQualificationAuthorizationTests(unittest.TestCase):
    def qualify(self, auth=None, review=None, **overrides):
        review = review or plan_review()
        plan_hash = canonical_digest(review)
        auth = auth or authorization(plan_hash)
        return validate_cloudflare_real_qualification_authorization(
            auth,
            review,
            expected_authorization_sha256=overrides.get("auth_hash", canonical_digest(auth)),
            expected_plan_review_sha256=overrides.get("plan_hash", plan_hash),
            expected_current_main_sha=overrides.get("main", MAIN),
            expected_scaffold_sha256=overrides.get("scaffold", SCAFFOLD),
            expected_node_review_sha256=overrides.get("node", NODE),
            expected_control_center_decision_id=overrides.get("decision", DECISION),
        )

    def test_exact_authorization_passes_without_execution(self):
        result = self.qualify()
        self.assertEqual(result["validation_status"], "PASS")
        self.assertTrue(result["single_use"])
        self.assertFalse(result["execution_consumed"])
        self.assertFalse(result["qualification_execution_allowed_by_validator"])
        self.assertEqual(result["real_cloudflare_requests"], 0)
        self.assertFalse(result["provider_qualified"])

    def test_external_hashes_are_trust_roots(self):
        for kwargs, reason in (
            ({"auth_hash": "f" * 64}, "AUTHORIZATION_HASH_MISMATCH"),
            ({"plan_hash": "e" * 64}, "PLAN_REVIEW_HASH_MISMATCH"),
            ({"scaffold": "d" * 64}, "EVIDENCE_BINDING_MISMATCH"),
            ({"node": "c" * 64}, "EVIDENCE_BINDING_MISMATCH"),
        ):
            with self.subTest(kwargs=kwargs), self.assertRaisesRegex(
                CloudflareQualificationAuthorizationError, reason
            ):
                self.qualify(**kwargs)

    def test_main_and_decision_are_exact(self):
        with self.assertRaisesRegex(CloudflareQualificationAuthorizationError, "MAIN_MISMATCH"):
            self.qualify(main="f" * 40)
        with self.assertRaisesRegex(CloudflareQualificationAuthorizationError, "DECISION_ID_MISMATCH"):
            self.qualify(decision="OTHER")

    def test_plan_budgets_cannot_drift(self):
        review = plan_review()
        review["runtime_probe_budget"]["CREATE_POST"] = 2
        with self.assertRaisesRegex(CloudflareQualificationAuthorizationError, "RUNTIME_BUDGET_INVALID"):
            self.qualify(review=review)

    def test_authorization_budgets_cannot_expand(self):
        review = plan_review()
        ph = canonical_digest(review)
        for field, key in (
            ("resource_budget", "custom_routes"),
            ("admin_operation_budget", "CREATE_D1_DATABASE"),
            ("runtime_probe_budget", "CREATE_POST"),
            ("cleanup_operation_budget", "DELETE_D1_DATABASE"),
        ):
            auth = authorization(ph)
            auth[field][key] = 1 if auth[field][key] == 0 else auth[field][key] + 1
            with self.subTest(field=field), self.assertRaisesRegex(
                CloudflareQualificationAuthorizationError, "BUDGET_INVALID"
            ):
                self.qualify(auth=auth, review=review)

    def test_secret_names_are_exact_and_values_never_embedded(self):
        review = plan_review()
        ph = canonical_digest(review)
        auth = authorization(ph)
        auth["api_token_secret_name"] = "OTHER"
        with self.assertRaisesRegex(CloudflareQualificationAuthorizationError, "CREDENTIAL_BOUNDARY_INVALID"):
            self.qualify(auth=auth, review=review)
        auth = authorization(ph)
        auth["credential_value_embedded"] = True
        with self.assertRaisesRegex(CloudflareQualificationAuthorizationError, "CREDENTIAL_BOUNDARY_INVALID"):
            self.qualify(auth=auth, review=review)

    def test_cleanup_success_is_required_for_credit(self):
        review = plan_review()
        ph = canonical_digest(review)
        auth = authorization(ph)
        auth["qualification_credit_requires_cleanup_success"] = False
        with self.assertRaisesRegex(CloudflareQualificationAuthorizationError, "PROVIDER_BOUNDARY_INVALID"):
            self.qualify(auth=auth, review=review)

    def test_single_use_must_be_unconsumed(self):
        review = plan_review()
        ph = canonical_digest(review)
        auth = authorization(ph)
        auth["execution_consumed"] = True
        with self.assertRaisesRegex(CloudflareQualificationAuthorizationError, "SINGLE_USE_BOUNDARY_INVALID"):
            self.qualify(auth=auth, review=review)

    def test_authorization_cannot_claim_execution_or_credit(self):
        review = plan_review()
        ph = canonical_digest(review)
        for field, bad in (
            ("qualification_execution_performed", True),
            ("real_cloudflare_requests", 1),
            ("credentials_read", 1),
            ("resources_created", 1),
            ("provider_qualified", True),
            ("production_credit", 1),
            ("cer081_credit", 1),
        ):
            auth = authorization(ph)
            auth[field] = bad
            with self.subTest(field=field), self.assertRaisesRegex(
                CloudflareQualificationAuthorizationError, "PREMATURE_EXECUTION_OR_CREDIT"
            ):
                self.qualify(auth=auth, review=review)


if __name__ == "__main__":
    unittest.main()

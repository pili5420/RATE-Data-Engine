"""Tests for real GitHub marker creation authorization qualification."""
import unittest

from src.intraday_activation_candidate_review import canonical_digest
from src.intraday_cloudflare_github_marker_adapter import marker_ref
from src.intraday_cloudflare_real_github_marker_authorization import (
    ALLOWED_OPERATIONS,
    MarkerCreationAuthorizationError,
    validate_marker_creation_authorization,
)

MAIN = "1" * 40


def cloudflare_auth():
    return {
        "artifact": "RATE_CLOUDFLARE_D1_REAL_PROVIDER_QUALIFICATION_AUTHORIZATION_QUALIFICATION_V1",
        "validation_status": "PASS",
        "authorization_sha256": "2" * 64,
        "plan_review_sha256": "3" * 64,
        "scaffold_sha256": "4" * 64,
        "node_review_sha256": "5" * 64,
        "current_main_sha": MAIN,
        "control_center_decision_id": "CC-CF-QUAL-2026-11-04",
        "provider": "CLOUDFLARE_WORKERS_D1",
        "plan": "WORKERS_FREE",
        "single_use": True,
        "execution_consumed": False,
        "automatic_retry_allowed": False,
        "fallback_allowed": False,
        "resource_budget": {},
        "admin_operation_budget": {},
        "runtime_probe_budget": {},
        "cleanup_operation_budget": {},
        "consumption_marker": {},
        "cleanup_required": True,
        "qualification_credit_requires_cleanup_success": True,
        "qualification_execution_allowed_by_validator": False,
        "qualification_execution_performed": False,
        "real_cloudflare_requests": 0,
        "credentials_read": 0,
        "resources_created": 0,
        "provider_qualified": False,
        "production_credit": 0,
        "cer081_credit": 0,
        "next_gate": "SEPARATE_CLOUDFLARE_REAL_QUALIFICATION_EXECUTOR",
    }


def authorization(cf_hash):
    return {
        "artifact": "RATE_CLOUDFLARE_REAL_GITHUB_MARKER_CREATION_AUTHORIZATION_V1",
        "status": "REAL_GITHUB_MARKER_CREATION_AUTHORIZED",
        "cloudflare_authorization_qualification_sha256": cf_hash,
        "current_main_sha": MAIN,
        "marker_ref": marker_ref("2" * 64),
        "marker_target_sha": MAIN,
        "single_use": True,
        "marker_creation_consumed": False,
        "automatic_retry_allowed": False,
        "fallback_allowed": False,
        "allowed_operations": list(ALLOWED_OPERATIONS),
        "create_count": 1,
        "update_count": 0,
        "delete_count": 0,
        "readback_required": True,
        "main_ref_update_allowed": False,
        "branch_ref_create_allowed": False,
        "pull_request_creation_allowed": False,
        "merge_allowed": False,
        "cloudflare_requests_allowed_before_marker": 0,
    }


class MarkerCreationAuthorizationTests(unittest.TestCase):
    def qualify(self, auth=None, cf=None, **overrides):
        cf = cf or cloudflare_auth()
        cf_hash = canonical_digest(cf)
        auth = auth or authorization(cf_hash)
        return validate_marker_creation_authorization(
            auth,
            cf,
            expected_authorization_sha256=overrides.get("auth_hash", canonical_digest(auth)),
            expected_cloudflare_authorization_sha256=overrides.get("cf_hash", cf_hash),
            expected_current_main_sha=overrides.get("main", MAIN),
        )

    def test_exact_authorization_passes_without_execution(self):
        r = self.qualify()
        self.assertEqual(r["validation_status"], "PASS")
        self.assertFalse(r["marker_creation_consumed"])
        self.assertFalse(r["execution_performed"])
        self.assertEqual(r["allowed_operations"], list(ALLOWED_OPERATIONS))
        self.assertEqual(r["real_github_requests"], 0)

    def test_external_hashes_are_trust_roots(self):
        with self.assertRaisesRegex(MarkerCreationAuthorizationError, "HASH_MISMATCH"):
            self.qualify(auth_hash="f" * 64)
        with self.assertRaisesRegex(MarkerCreationAuthorizationError, "CLOUDFLARE_AUTH_HASH_MISMATCH"):
            self.qualify(cf_hash="e" * 64)

    def test_marker_ref_is_derived_from_cloudflare_authorization(self):
        cf = cloudflare_auth()
        cf["authorization_sha256"] = "a" * 64
        auth = authorization(canonical_digest(cf))
        with self.assertRaisesRegex(MarkerCreationAuthorizationError, "REF_BINDING_MISMATCH"):
            self.qualify(auth=auth, cf=cf)

    def test_main_drift_fails(self):
        with self.assertRaisesRegex(MarkerCreationAuthorizationError, "CLOUDFLARE_MAIN_MISMATCH"):
            self.qualify(main="f" * 40)

    def test_consumed_or_retry_enabled_fails(self):
        cf = cloudflare_auth()
        cfh = canonical_digest(cf)
        auth = authorization(cfh)
        auth["marker_creation_consumed"] = True
        with self.assertRaisesRegex(MarkerCreationAuthorizationError, "SINGLE_USE_BOUNDARY_INVALID"):
            self.qualify(auth=auth, cf=cf)
        auth = authorization(cfh)
        auth["automatic_retry_allowed"] = True
        with self.assertRaisesRegex(MarkerCreationAuthorizationError, "SINGLE_USE_BOUNDARY_INVALID"):
            self.qualify(auth=auth, cf=cf)

    def test_operations_and_budgets_are_exact(self):
        cf = cloudflare_auth()
        cfh = canonical_digest(cf)
        auth = authorization(cfh)
        auth["allowed_operations"].append("DELETE_REF")
        with self.assertRaisesRegex(MarkerCreationAuthorizationError, "OPERATIONS_INVALID"):
            self.qualify(auth=auth, cf=cf)
        auth = authorization(cfh)
        auth["create_count"] = 2
        with self.assertRaisesRegex(MarkerCreationAuthorizationError, "BUDGET_INVALID"):
            self.qualify(auth=auth, cf=cf)

    def test_forbidden_actions_remain_false(self):
        cf = cloudflare_auth()
        cfh = canonical_digest(cf)
        for field in (
            "main_ref_update_allowed",
            "branch_ref_create_allowed",
            "pull_request_creation_allowed",
            "merge_allowed",
        ):
            auth = authorization(cfh)
            auth[field] = True
            with self.subTest(field=field), self.assertRaisesRegex(
                MarkerCreationAuthorizationError, "FORBIDDEN_ACTION_BOUNDARY_INVALID"
            ):
                self.qualify(auth=auth, cf=cf)


if __name__ == "__main__":
    unittest.main()

"""Tests for synthetic rehearsal of the one-shot Cloudflare qualification executor."""
from __future__ import annotations

import unittest

from src.intraday_activation_candidate_review import canonical_digest
from src.intraday_cloudflare_d1_real_qualification_authorization import (
    EXPECTED_ADMIN_BUDGET,
    EXPECTED_CLEANUP_BUDGET,
    EXPECTED_RESOURCE_BUDGET,
    EXPECTED_RUNTIME_BUDGET,
)
from src.intraday_cloudflare_d1_qualification_executor_rehearsal import (
    CloudflareQualificationRehearsalError,
    SyntheticCloudflareQualificationBackend,
    rehearse_cloudflare_real_qualification,
)

MAIN = "1" * 40


def qualification():
    return {
        "artifact": "RATE_CLOUDFLARE_D1_REAL_PROVIDER_QUALIFICATION_AUTHORIZATION_QUALIFICATION_V1",
        "validation_status": "PASS",
        "authorization_sha256": "2" * 64,
        "plan_review_sha256": "3" * 64,
        "scaffold_sha256": "4" * 64,
        "node_review_sha256": "5" * 64,
        "current_main_sha": MAIN,
        "control_center_decision_id": "CC-CF-D1-QUAL-2026-11-04",
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


class CloudflareQualificationRehearsalTests(unittest.TestCase):
    def run_rehearsal(self, backend=None, q=None, **overrides):
        q = q or qualification()
        backend = backend or SyntheticCloudflareQualificationBackend()
        result = rehearse_cloudflare_real_qualification(
            q,
            backend,
            expected_qualification_sha256=overrides.get("hash", canonical_digest(q)),
            expected_current_main_sha=overrides.get("main", MAIN),
        )
        return result, backend, q

    def test_success_sequence_consumes_once_probes_and_cleans_all_resources(self):
        result, backend, _ = self.run_rehearsal()
        self.assertEqual(result["validation_status"], "PASS")
        self.assertEqual(result["disposition"], "READY_FOR_REAL_CLOUDFLARE_QUALIFICATION_EXECUTOR")
        self.assertTrue(result["single_use_consumed"])
        self.assertFalse(result["retry_allowed"])
        self.assertEqual(len(result["admin_calls"]), 9)
        self.assertEqual(len(result["runtime_calls"]), 6)
        self.assertEqual(result["cleanup_attempts"]["DELETE_WORKER_SCRIPT"], 1)
        self.assertEqual(result["cleanup_attempts"]["DELETE_D1_DATABASE"], 1)
        self.assertFalse(result["residual_resources"])
        self.assertFalse(backend.worker_exists)
        self.assertFalse(backend.d1_exists)

    def test_preflight_hash_and_main_drift_fail_before_consume(self):
        q = qualification()
        for kwargs, reason in (
            ({"hash": "f" * 64}, "QUALIFICATION_HASH_MISMATCH"),
            ({"main": "f" * 40}, "MAIN_MISMATCH"),
        ):
            backend = SyntheticCloudflareQualificationBackend()
            with self.subTest(kwargs=kwargs), self.assertRaisesRegex(
                CloudflareQualificationRehearsalError, reason
            ):
                rehearse_cloudflare_real_qualification(
                    q, backend,
                    expected_qualification_sha256=kwargs.get("hash", canonical_digest(q)),
                    expected_current_main_sha=kwargs.get("main", MAIN),
                )
            self.assertEqual(backend.consumed, set())
            self.assertEqual(backend.calls, [])

    def test_replay_is_rejected_before_new_calls(self):
        backend = SyntheticCloudflareQualificationBackend()
        result, backend, q = self.run_rehearsal(backend=backend)
        calls = list(backend.calls)
        with self.assertRaisesRegex(
            CloudflareQualificationRehearsalError, "SINGLE_USE_ALREADY_CONSUMED"
        ):
            rehearse_cloudflare_real_qualification(
                q, backend,
                expected_qualification_sha256=canonical_digest(q),
                expected_current_main_sha=MAIN,
            )
        self.assertEqual(backend.calls, calls)

    def test_failure_after_d1_creation_cleans_d1_once_and_is_non_retryable(self):
        backend = SyntheticCloudflareQualificationBackend(fail_at="UPLOAD_WORKER_MODULE")
        result, backend, q = self.run_rehearsal(backend=backend)
        self.assertEqual(result["validation_status"], "BLOCKED")
        self.assertEqual(result["disposition"], "BLOCKED_SYNTHETIC_OPERATION_FAILURE")
        self.assertEqual(result["cleanup_attempts"]["DELETE_D1_DATABASE"], 1)
        self.assertEqual(result["cleanup_attempts"]["DELETE_WORKER_SCRIPT"], 0)
        self.assertFalse(result["residual_resources"])
        with self.assertRaisesRegex(CloudflareQualificationRehearsalError, "SINGLE_USE_ALREADY_CONSUMED"):
            rehearse_cloudflare_real_qualification(
                q, backend,
                expected_qualification_sha256=canonical_digest(q),
                expected_current_main_sha=MAIN,
            )

    def test_runtime_failure_cleans_worker_and_d1_once(self):
        backend = SyntheticCloudflareQualificationBackend(fail_at="DUPLICATE_POST")
        result, backend, _ = self.run_rehearsal(backend=backend)
        self.assertEqual(result["validation_status"], "BLOCKED")
        self.assertEqual(result["cleanup_attempts"]["DELETE_WORKER_SCRIPT"], 1)
        self.assertEqual(result["cleanup_attempts"]["DELETE_D1_DATABASE"], 1)
        self.assertFalse(result["residual_resources"])

    def test_cleanup_failure_blocks_with_residual_resource_and_no_cleanup_retry(self):
        backend = SyntheticCloudflareQualificationBackend(fail_at="DELETE_WORKER_SCRIPT")
        result, backend, _ = self.run_rehearsal(backend=backend)
        self.assertEqual(result["validation_status"], "BLOCKED")
        self.assertEqual(result["disposition"], "BLOCKED_RESIDUAL_RESOURCE")
        self.assertEqual(result["cleanup_attempts"]["DELETE_WORKER_SCRIPT"], 1)
        self.assertEqual(result["cleanup_attempts"]["DELETE_D1_DATABASE"], 1)
        self.assertTrue(result["residual_resources"])
        self.assertTrue(backend.worker_exists)
        self.assertFalse(backend.d1_exists)

    def test_cleanup_d1_failure_blocks_with_residual_d1(self):
        backend = SyntheticCloudflareQualificationBackend(fail_at="DELETE_D1_DATABASE")
        result, backend, _ = self.run_rehearsal(backend=backend)
        self.assertEqual(result["disposition"], "BLOCKED_RESIDUAL_RESOURCE")
        self.assertTrue(result["residual_resources"])
        self.assertTrue(backend.d1_exists)
        self.assertEqual(result["cleanup_attempts"]["DELETE_D1_DATABASE"], 1)

    def test_real_or_subclass_backend_is_forbidden(self):
        class SubclassBackend(SyntheticCloudflareQualificationBackend):
            pass
        q = qualification()
        with self.assertRaisesRegex(CloudflareQualificationRehearsalError, "REAL_BACKEND_FORBIDDEN"):
            rehearse_cloudflare_real_qualification(
                q, SubclassBackend(),
                expected_qualification_sha256=canonical_digest(q),
                expected_current_main_sha=MAIN,
            )

    def test_rehearsal_never_claims_real_provider_credit(self):
        result, _, _ = self.run_rehearsal()
        self.assertEqual(result["real_cloudflare_requests"], 0)
        self.assertEqual(result["credentials_read"], 0)
        self.assertEqual(result["real_resources_created"], 0)
        self.assertFalse(result["provider_qualified"])
        self.assertEqual(result["production_credit"], 0)
        self.assertEqual(result["cer081_credit"], 0)


if __name__ == "__main__":
    unittest.main()

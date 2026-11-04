"""Tests for the post-marker Cloudflare qualification orchestration."""
from __future__ import annotations

from copy import deepcopy
import unittest
from unittest.mock import patch

from src.intraday_activation_candidate_review import canonical_digest
from src.intraday_cloudflare_d1_deployment_scaffold import build_cloudflare_d1_scaffold
from src.intraday_cloudflare_d1_real_qualification_authorization import (
    EXPECTED_ADMIN_BUDGET,
    EXPECTED_CLEANUP_BUDGET,
    EXPECTED_RESOURCE_BUDGET,
    EXPECTED_RUNTIME_BUDGET,
)
from src.intraday_cloudflare_github_marker_adapter import (
    SyntheticGitHubRefTransport,
    marker_ref,
)
from src.intraday_cloudflare_post_marker_orchestrator import (
    PostMarkerOrchestrationError,
    rehearse_post_marker_cloudflare_qualification,
)
from src.intraday_cloudflare_real_github_marker_authorization import (
    ALLOWED_OPERATIONS,
    validate_marker_creation_authorization,
)
from src.intraday_cloudflare_real_github_marker_executor import execute_marker

MAIN = "1" * 40
REAL_AUTH_HASH = "2" * 64


def cloudflare_authorization():
    return {
        "artifact":"RATE_CLOUDFLARE_D1_REAL_PROVIDER_QUALIFICATION_AUTHORIZATION_QUALIFICATION_V1",
        "validation_status":"PASS",
        "authorization_sha256":REAL_AUTH_HASH,
        "plan_review_sha256":"3"*64,
        "scaffold_sha256":"4"*64,
        "node_review_sha256":"5"*64,
        "current_main_sha":MAIN,
        "control_center_decision_id":"CC-CF-D1-QUAL-2026-11-04",
        "provider":"CLOUDFLARE_WORKERS_D1",
        "plan":"WORKERS_FREE",
        "single_use":True,
        "execution_consumed":False,
        "automatic_retry_allowed":False,
        "fallback_allowed":False,
        "resource_budget":dict(EXPECTED_RESOURCE_BUDGET),
        "admin_operation_budget":dict(EXPECTED_ADMIN_BUDGET),
        "runtime_probe_budget":dict(EXPECTED_RUNTIME_BUDGET),
        "cleanup_operation_budget":dict(EXPECTED_CLEANUP_BUDGET),
        "cleanup_required":True,
        "qualification_credit_requires_cleanup_success":True,
        "qualification_execution_allowed_by_validator":False,
        "qualification_execution_performed":False,
        "real_cloudflare_requests":0,
        "credentials_read":0,
        "resources_created":0,
        "provider_qualified":False,
        "production_credit":0,
        "cer081_credit":0,
        "next_gate":"SEPARATE_CLOUDFLARE_REAL_QUALIFICATION_EXECUTOR",
    }


def candidate_qualification():
    return {
        "artifact":"RATE_INTRADAY_REAL_AUTHORITY_STORE_PROVIDER_CANDIDATE_QUALIFICATION_V1",
        "validation_status":"PASS",
        "provider":"CLOUDFLARE_WORKERS_D1",
        "plan":"WORKERS_FREE",
        "architecture":"AUTHENTICATED_WORKER_PROXY_PLUS_D1",
        "route_template":"/v1/execution-receipts/{execution_id}",
        "table":"rate_execution_receipts",
        "read_replication":"DISABLED",
        "atomic_create_if_absent":True,
        "strong_read_after_write":True,
        "overwrite_allowed":False,
        "delete_allowed":False,
        "ambiguous_create_policy":"READ_SAME_EXECUTION_ID_DO_NOT_RETRY_CREATE",
        "credential_secret_name":"RATE_D1_RECEIPT_WORKER_TOKEN",
        "provider_selected_for_live_qualification":True,
        "provider_qualified":False,
        "real_provider_requests":0,
        "credentials_read":0,
        "resources_created":0,
        "production_eligible":False,
        "external_dependency_resolved":False,
        "production_credit":0,
        "cer081_credit":0,
        "next_gate":"CLOUDFLARE_D1_REAL_PROVIDER_QUALIFICATION",
    }


def scaffold():
    q = candidate_qualification()
    return build_cloudflare_d1_scaffold(
        q,
        expected_candidate_qualification_sha256=canonical_digest(q),
    )["files"]


def marker_chain(cf=None):
    cf = cf or cloudflare_authorization()
    cf_hash = canonical_digest(cf)
    marker_auth = {
        "artifact":"RATE_CLOUDFLARE_REAL_GITHUB_MARKER_CREATION_AUTHORIZATION_V1",
        "status":"REAL_GITHUB_MARKER_CREATION_AUTHORIZED",
        "cloudflare_authorization_qualification_sha256":cf_hash,
        "cloudflare_real_qualification_authorization_sha256":cf["authorization_sha256"],
        "current_main_sha":MAIN,
        "marker_ref":marker_ref(cf["authorization_sha256"]),
        "marker_target_sha":MAIN,
        "single_use":True,
        "marker_creation_consumed":False,
        "automatic_retry_allowed":False,
        "fallback_allowed":False,
        "allowed_operations":list(ALLOWED_OPERATIONS),
        "create_count":1,
        "update_count":0,
        "delete_count":0,
        "readback_required":True,
        "main_ref_update_allowed":False,
        "branch_ref_create_allowed":False,
        "pull_request_creation_allowed":False,
        "merge_allowed":False,
        "cloudflare_requests_allowed_before_marker":0,
    }
    marker_qual = validate_marker_creation_authorization(
        marker_auth,
        cf,
        expected_authorization_sha256=canonical_digest(marker_auth),
        expected_cloudflare_authorization_sha256=cf_hash,
        expected_current_main_sha=MAIN,
    )
    marker_qual_hash = canonical_digest(marker_qual)
    marker_result = execute_marker(
        marker_qual,
        SyntheticGitHubRefTransport(),
        expected_authorization_qualification_sha256=marker_qual_hash,
    )
    return marker_qual, marker_result


class PostMarkerOrchestratorTests(unittest.TestCase):
    def run_orchestrator(self, cf=None, marker_auth=None, marker_result=None, **overrides):
        cf = cf or cloudflare_authorization()
        if marker_auth is None or marker_result is None:
            marker_auth, marker_result = marker_chain(cf)
        return rehearse_post_marker_cloudflare_qualification(
            cf,
            marker_auth,
            marker_result,
            scaffold(),
            expected_cloudflare_authorization_qualification_sha256=overrides.get(
                "cf_hash", canonical_digest(cf)
            ),
            expected_marker_authorization_qualification_sha256=overrides.get(
                "marker_auth_hash", canonical_digest(marker_auth)
            ),
            expected_marker_execution_result_sha256=overrides.get(
                "marker_result_hash", canonical_digest(marker_result)
            ),
            expected_current_main_sha=overrides.get("main", MAIN),
        )

    def test_complete_marker_then_17_request_chain_passes(self):
        r = self.run_orchestrator()
        self.assertEqual(r["validation_status"], "PASS")
        self.assertTrue(r["marker_gate_passed"])
        self.assertEqual(r["cloudflare_requests_before_marker"], 0)
        self.assertEqual(r["synthetic_cloudflare_requests_after_marker"], 17)
        self.assertEqual(r["admin_requests"], 11)
        self.assertEqual(r["worker_requests"], 6)
        self.assertEqual(r["real_cloudflare_requests"], 0)
        self.assertFalse(r["provider_qualified"])

    def test_marker_result_hash_drift_blocks_before_https_chain(self):
        marker_auth, marker_result = marker_chain()
        with patch(
            "src.intraday_cloudflare_post_marker_orchestrator."
            "review_cloudflare_https_transport_integration",
            side_effect=AssertionError("HTTPS_CHAIN_STARTED_TOO_EARLY"),
        ) as downstream:
            with self.assertRaisesRegex(
                PostMarkerOrchestrationError,
                "MARKER_RESULT_HASH_MISMATCH",
            ):
                self.run_orchestrator(
                    marker_auth=marker_auth,
                    marker_result=marker_result,
                    marker_result_hash="f" * 64,
                )
        downstream.assert_not_called()

    def test_unconsumed_marker_blocks_before_https_chain(self):
        marker_auth, marker_result = marker_chain()
        marker_result = deepcopy(marker_result)
        marker_result["marker_creation_consumed"] = False
        with patch(
            "src.intraday_cloudflare_post_marker_orchestrator."
            "review_cloudflare_https_transport_integration",
            side_effect=AssertionError("HTTPS_CHAIN_STARTED_TOO_EARLY"),
        ) as downstream:
            with self.assertRaisesRegex(
                PostMarkerOrchestrationError,
                "MARKER_EXECUTION_BOUNDARY_INVALID",
            ):
                self.run_orchestrator(
                    marker_auth=marker_auth,
                    marker_result=marker_result,
                    marker_result_hash=canonical_digest(marker_result),
                )
        downstream.assert_not_called()

    def test_marker_target_drift_blocks_before_https_chain(self):
        marker_auth, marker_result = marker_chain()
        marker_result = deepcopy(marker_result)
        marker_result["marker_target_sha"] = "f" * 40
        with patch(
            "src.intraday_cloudflare_post_marker_orchestrator."
            "review_cloudflare_https_transport_integration",
            side_effect=AssertionError("HTTPS_CHAIN_STARTED_TOO_EARLY"),
        ) as downstream:
            with self.assertRaisesRegex(
                PostMarkerOrchestrationError,
                "MARKER_RESULT_BINDING_MISMATCH",
            ):
                self.run_orchestrator(
                    marker_auth=marker_auth,
                    marker_result=marker_result,
                    marker_result_hash=canonical_digest(marker_result),
                )
        downstream.assert_not_called()

    def test_cloudflare_authorization_main_drift_fails_closed(self):
        with self.assertRaisesRegex(
            PostMarkerOrchestrationError,
            "CLOUDFLARE_AUTH_NOT_PASS",
        ):
            self.run_orchestrator(main="f" * 40)

    def test_synthetic_chain_never_claims_real_execution_or_credit(self):
        r = self.run_orchestrator()
        self.assertEqual(r["real_github_requests"], 0)
        self.assertFalse(r["real_git_ref_created"])
        self.assertEqual(r["real_network_requests"], 0)
        self.assertEqual(r["real_cloudflare_requests"], 0)
        self.assertEqual(r["credentials_read"], 0)
        self.assertEqual(r["real_resources_created"], 0)
        self.assertEqual(r["production_credit"], 0)
        self.assertEqual(r["cer081_credit"], 0)


if __name__ == "__main__":
    unittest.main()

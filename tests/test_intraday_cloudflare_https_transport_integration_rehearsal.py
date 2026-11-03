"""Integration tests for Cloudflare request shapes through the bounded HTTPS transport."""
from __future__ import annotations

import unittest

from src.intraday_activation_candidate_review import canonical_digest
from src.intraday_cloudflare_d1_deployment_scaffold import build_cloudflare_d1_scaffold
from src.intraday_cloudflare_d1_real_qualification_authorization import (
    EXPECTED_ADMIN_BUDGET,
    EXPECTED_CLEANUP_BUDGET,
    EXPECTED_RESOURCE_BUDGET,
    EXPECTED_RUNTIME_BUDGET,
)
from src.intraday_cloudflare_https_transport_integration_rehearsal import (
    review_cloudflare_https_transport_integration,
)

MAIN="1"*40


def authorization():
    return {
        "artifact":"RATE_CLOUDFLARE_D1_REAL_PROVIDER_QUALIFICATION_AUTHORIZATION_QUALIFICATION_V1",
        "validation_status":"PASS",
        "authorization_sha256":"2"*64,
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
    q=candidate_qualification()
    return build_cloudflare_d1_scaffold(
        q,expected_candidate_qualification_sha256=canonical_digest(q)
    )["files"]


class HTTPSIntegrationTests(unittest.TestCase):
    def review(self, auth=None, **overrides):
        auth=auth or authorization()
        return review_cloudflare_https_transport_integration(
            auth,
            scaffold(),
            expected_authorization_qualification_sha256=overrides.get("hash",canonical_digest(auth)),
            expected_current_main_sha=overrides.get("main",MAIN),
        )

    def test_full_17_request_sequence_passes_through_bounded_transport(self):
        result=self.review()
        self.assertEqual(result["validation_status"],"PASS")
        self.assertEqual(result["total_requests"],17)
        self.assertEqual(result["admin_requests"],11)
        self.assertEqual(result["worker_requests"],6)
        self.assertEqual(result["connections_created"],17)
        self.assertEqual(result["connections_closed"],17)
        self.assertTrue(result["tls_hostname_verification_all"])
        self.assertEqual(result["retry_count"],0)
        self.assertEqual(result["redirects_followed"],0)
        self.assertEqual(result["real_network_requests"],0)

    def test_authorization_hash_drift_fails_before_any_real_network(self):
        with self.assertRaises(Exception):
            self.review(hash="f"*64)

    def test_main_drift_fails_closed(self):
        with self.assertRaises(Exception):
            self.review(main="f"*40)

    def test_rehearsal_never_claims_provider_or_production_credit(self):
        result=self.review()
        self.assertFalse(result["provider_qualified"])
        self.assertEqual(result["real_cloudflare_requests"],0)
        self.assertEqual(result["credentials_read"],0)
        self.assertEqual(result["real_resources_created"],0)
        self.assertEqual(result["production_credit"],0)
        self.assertEqual(result["cer081_credit"],0)


if __name__=="__main__":
    unittest.main()

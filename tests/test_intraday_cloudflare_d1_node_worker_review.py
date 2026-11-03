"""Tests for actual generated Worker JavaScript execution under Node."""
from __future__ import annotations

from copy import deepcopy
import unittest

from src.intraday_activation_candidate_review import canonical_digest
from src.intraday_cloudflare_d1_deployment_scaffold import (
    EXPECTED_FILES,
    build_cloudflare_d1_scaffold,
)
from src.intraday_cloudflare_d1_node_worker_review import (
    D1NodeWorkerReviewError,
    review_cloudflare_d1_node_worker,
)


def qualification():
    return {
        "artifact": "RATE_INTRADAY_REAL_AUTHORITY_STORE_PROVIDER_CANDIDATE_QUALIFICATION_V1",
        "validation_status": "PASS",
        "provider": "CLOUDFLARE_WORKERS_D1",
        "plan": "WORKERS_FREE",
        "architecture": "AUTHENTICATED_WORKER_PROXY_PLUS_D1",
        "route_template": "/v1/execution-receipts/{execution_id}",
        "table": "rate_execution_receipts",
        "read_replication": "DISABLED",
        "atomic_create_if_absent": True,
        "strong_read_after_write": True,
        "overwrite_allowed": False,
        "delete_allowed": False,
        "ambiguous_create_policy": "READ_SAME_EXECUTION_ID_DO_NOT_RETRY_CREATE",
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


def files():
    q = qualification()
    return build_cloudflare_d1_scaffold(
        q, expected_candidate_qualification_sha256=canonical_digest(q)
    )["files"]


class D1NodeWorkerReviewTests(unittest.TestCase):
    def test_actual_worker_source_passes_node_semantic_review(self):
        result = review_cloudflare_d1_node_worker(files())
        self.assertEqual(result["validation_status"], "PASS")
        self.assertEqual(result["runtime"], "NODE_EXECUTED_ACTUAL_WORKER_MJS")
        self.assertEqual(result["create_status"], 201)
        self.assertEqual(result["duplicate_status"], 409)
        self.assertEqual(result["database_failure_status"], 503)
        self.assertEqual(result["insert_retries"], 0)
        self.assertEqual(result["outbound_network_requests"], 0)
        self.assertFalse(result["provider_qualified"])

    def test_duplicate_success_tamper_is_detected_by_node_review(self):
        altered = deepcopy(files())
        altered[EXPECTED_FILES[0]] = altered[EXPECTED_FILES[0]].replace(
            'return json({ error: "ALREADY_EXISTS" }, 409);',
            'return json({ error: "ALREADY_EXISTS" }, 200);',
        )
        with self.assertRaisesRegex(
            D1NodeWorkerReviewError, "DUPLICATE_NOT_FAIL_CLOSED"
        ):
            review_cloudflare_d1_node_worker(altered)

    def test_database_failure_success_tamper_is_detected(self):
        altered = deepcopy(files())
        altered[EXPECTED_FILES[0]] = altered[EXPECTED_FILES[0]].replace(
            'return json({ error: "D1_CREATE_FAILED" }, 503);',
            'return json({ error: "D1_CREATE_FAILED" }, 201);',
        )
        with self.assertRaisesRegex(
            D1NodeWorkerReviewError, "DATABASE_FAILURE_INVALID"
        ):
            review_cloudflare_d1_node_worker(altered)

    def test_static_outbound_fetch_tamper_fails_before_node(self):
        altered = deepcopy(files())
        altered[EXPECTED_FILES[0]] += "\nawait fetch('https://example.invalid');\n"
        with self.assertRaisesRegex(Exception, "WORKER_FORBIDDEN_BEHAVIOR"):
            review_cloudflare_d1_node_worker(altered)


if __name__ == "__main__":
    unittest.main()

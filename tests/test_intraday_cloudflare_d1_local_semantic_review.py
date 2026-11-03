"""Tests for local Worker + D1 scaffold semantics."""
from __future__ import annotations

from copy import deepcopy
import sqlite3
import unittest

from src.intraday_activation_candidate_review import canonical_digest
from src.intraday_cloudflare_d1_deployment_scaffold import (
    EXPECTED_FILES,
    build_cloudflare_d1_scaffold,
)
from src.intraday_cloudflare_d1_local_semantic_review import (
    D1LocalSemanticError,
    LocalWorkerD1Model,
    client_post_with_ambiguous_transport_readback,
    review_cloudflare_d1_local_semantics,
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


def receipt_body(execution_id="RATE-LOCAL-001", value=1, digest="a"):
    return {
        "execution_id": execution_id,
        "receipt_json": {"state": "CONSUMED_BEFORE_GIT_MUTATION", "value": value},
        "receipt_sha256": digest * 64,
    }


class D1LocalSemanticTests(unittest.TestCase):
    def test_full_local_semantic_review_passes_without_cloudflare(self):
        result = review_cloudflare_d1_local_semantics(files())
        self.assertEqual(result["validation_status"], "PASS")
        self.assertEqual(result["duplicate_primary_key_status"], 409)
        self.assertEqual(result["update_guard"], "PASS")
        self.assertEqual(result["delete_guard"], "PASS")
        self.assertEqual(
            result["ambiguous_http_outcome"]["outcome"],
            "AMBIGUOUS_HTTP_CONFIRMED_BY_GET",
        )
        self.assertEqual(result["real_cloudflare_requests"], 0)
        self.assertFalse(result["provider_qualified"])

    def test_duplicate_same_receipt_is_409_not_success(self):
        worker = LocalWorkerD1Model(files()[EXPECTED_FILES[1]])
        try:
            body = receipt_body()
            self.assertEqual(worker.request(
                "POST", "/v1/execution-receipts/RATE-LOCAL-001",
                "Bearer synthetic-token", body,
            )[0], 201)
            self.assertEqual(worker.request(
                "POST", "/v1/execution-receipts/RATE-LOCAL-001",
                "Bearer synthetic-token", body,
            )[0], 409)
            self.assertEqual(worker.insert_attempts, 2)
        finally:
            worker.close()

    def test_duplicate_different_receipt_is_also_409_and_original_survives(self):
        worker = LocalWorkerD1Model(files()[EXPECTED_FILES[1]])
        try:
            first = receipt_body()
            second = receipt_body(value=2, digest="b")
            self.assertEqual(worker.request(
                "POST", "/v1/execution-receipts/RATE-LOCAL-001",
                "Bearer synthetic-token", first,
            )[0], 201)
            self.assertEqual(worker.request(
                "POST", "/v1/execution-receipts/RATE-LOCAL-001",
                "Bearer synthetic-token", second,
            )[0], 409)
            status, payload = worker.request(
                "GET", "/v1/execution-receipts/RATE-LOCAL-001",
                "Bearer synthetic-token",
            )
            self.assertEqual(status, 200)
            self.assertEqual(payload["receipt_sha256"], "a" * 64)
            self.assertEqual(payload["receipt_json"]["value"], 1)
        finally:
            worker.close()

    def test_update_and_delete_triggers_abort(self):
        worker = LocalWorkerD1Model(files()[EXPECTED_FILES[1]])
        try:
            body = receipt_body()
            worker.request(
                "POST", "/v1/execution-receipts/RATE-LOCAL-001",
                "Bearer synthetic-token", body,
            )
            for op in ("update", "delete"):
                with self.subTest(op=op), self.assertRaisesRegex(
                    sqlite3.DatabaseError, "IMMUTABLE_RECEIPT"
                ):
                    if op == "update":
                        worker.raw_update("RATE-LOCAL-001", "{}")
                    else:
                        worker.raw_delete("RATE-LOCAL-001")
        finally:
            worker.close()

    def test_auth_route_and_method_fail_closed(self):
        worker = LocalWorkerD1Model(files()[EXPECTED_FILES[1]])
        try:
            self.assertEqual(worker.request(
                "GET", "/v1/execution-receipts/RATE-LOCAL-001", "Bearer wrong"
            )[0], 401)
            self.assertEqual(worker.request(
                "GET", "/v1/execution-receipts/BAD..ID", "Bearer synthetic-token"
            )[0], 404)
            self.assertEqual(worker.request(
                "DELETE", "/v1/execution-receipts/RATE-LOCAL-001", "Bearer synthetic-token"
            )[0], 405)
        finally:
            worker.close()

    def test_invalid_receipt_is_rejected_before_insert(self):
        worker = LocalWorkerD1Model(files()[EXPECTED_FILES[1]])
        try:
            body = receipt_body()
            body["receipt_sha256"] = "bad"
            status, _ = worker.request(
                "POST", "/v1/execution-receipts/RATE-LOCAL-001",
                "Bearer synthetic-token", body,
            )
            self.assertEqual(status, 400)
            self.assertEqual(worker.insert_attempts, 0)
        finally:
            worker.close()

    def test_database_failure_before_insert_returns_503_without_row(self):
        worker = LocalWorkerD1Model(files()[EXPECTED_FILES[1]])
        try:
            body = receipt_body()
            status, _ = worker.request(
                "POST", "/v1/execution-receipts/RATE-LOCAL-001",
                "Bearer synthetic-token", body, fail_before_insert=True,
            )
            self.assertEqual(status, 503)
            self.assertEqual(worker.request(
                "GET", "/v1/execution-receipts/RATE-LOCAL-001",
                "Bearer synthetic-token",
            )[0], 404)
        finally:
            worker.close()

    def test_ambiguous_http_outcome_uses_one_post_then_one_get(self):
        worker = LocalWorkerD1Model(files()[EXPECTED_FILES[1]])
        try:
            result = client_post_with_ambiguous_transport_readback(
                worker,
                execution_id="RATE-LOCAL-AMBIG",
                body=receipt_body("RATE-LOCAL-AMBIG"),
            )
            self.assertEqual(result["post_calls"], 1)
            self.assertEqual(result["get_calls"], 1)
            self.assertEqual(result["insert_attempts"], 1)
            self.assertEqual(result["post_retries"], 0)
        finally:
            worker.close()

    def test_schema_without_delete_guard_fails_full_review(self):
        altered = deepcopy(files())
        altered[EXPECTED_FILES[1]] = altered[EXPECTED_FILES[1]].replace(
            "BEFORE DELETE ON rate_execution_receipts",
            "BEFORE SELECT ON rate_execution_receipts",
        )
        with self.assertRaises(Exception):
            review_cloudflare_d1_local_semantics(altered)


if __name__ == "__main__":
    unittest.main()

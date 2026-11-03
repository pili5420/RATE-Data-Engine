"""Tests for exact Cloudflare HTTP request shapes using synthetic transport."""
from __future__ import annotations

import json
import unittest
from urllib.parse import urlparse

from src.intraday_activation_candidate_review import canonical_digest
from src.intraday_cloudflare_d1_deployment_scaffold import build_cloudflare_d1_scaffold
from src.intraday_cloudflare_d1_real_qualification_authorization import (
    EXPECTED_ADMIN_BUDGET,
    EXPECTED_CLEANUP_BUDGET,
    EXPECTED_RESOURCE_BUDGET,
    EXPECTED_RUNTIME_BUDGET,
)
from src.intraday_cloudflare_d1_http_request_shape_rehearsal import (
    ADMIN_TOKEN,
    ACCOUNT_ID,
    CloudflareHTTPRequestShapeError,
    SyntheticCloudflareHTTPTransport,
    WORKER_TOKEN,
    rehearse_cloudflare_http_request_shapes,
)

MAIN = "1" * 40


def authorization():
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


def candidate_qualification():
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


def scaffold_files():
    q=candidate_qualification()
    return build_cloudflare_d1_scaffold(q, expected_candidate_qualification_sha256=canonical_digest(q))["files"]


class CloudflareHTTPRequestShapeTests(unittest.TestCase):
    def rehearse(self, auth=None, transport=None, **overrides):
        auth=auth or authorization()
        transport=transport or SyntheticCloudflareHTTPTransport()
        result=rehearse_cloudflare_http_request_shapes(
            auth,
            scaffold_files(),
            transport,
            expected_authorization_qualification_sha256=overrides.get("hash",canonical_digest(auth)),
            expected_current_main_sha=overrides.get("main",MAIN),
        )
        return result,transport,auth

    def test_exact_request_sequence_passes_without_real_network(self):
        result,transport,_=self.rehearse()
        self.assertEqual(result["validation_status"],"PASS")
        self.assertEqual(result["request_count"],17)
        self.assertEqual(result["admin_and_cleanup_requests"],11)
        self.assertEqual(result["runtime_requests"],6)
        self.assertEqual(result["retry_count"],0)
        self.assertEqual(result["real_network_requests"],0)
        self.assertFalse(result["provider_qualified"])
        self.assertFalse(transport.d1_exists)
        self.assertFalse(transport.worker_exists)

    def test_d1_create_and_schema_query_shapes_are_exact(self):
        _,transport,_=self.rehearse()
        create=transport.calls[0]
        self.assertEqual(create["method"],"POST")
        self.assertTrue(create["url"].endswith(f"/accounts/{ACCOUNT_ID}/d1/database"))
        payload=json.loads(create["body"].decode())
        self.assertEqual(payload["read_replication"],{"mode":"disabled"})
        query=[c for c in transport.calls if c["url"].endswith("/query")][0]
        q=json.loads(query["body"].decode())
        self.assertIn("rate_execution_receipts",q["sql"])
        self.assertEqual(q["params"],[])

    def test_worker_multipart_contains_exact_d1_binding_and_no_worker_secret(self):
        _,transport,_=self.rehearse()
        upload=transport.calls[1]
        text=upload["body"].decode()
        self.assertIn('"main_module":"worker.mjs"',text)
        self.assertIn('"type":"d1"',text)
        self.assertIn('"name":"DB"',text)
        self.assertIn('"database_id":"11111111-1111-1111-1111-111111111111"',text)
        self.assertNotIn(WORKER_TOKEN,text)

    def test_admin_token_never_reaches_workers_dev_and_worker_token_not_admin_header(self):
        _,transport,_=self.rehearse()
        for call in transport.calls:
            host=urlparse(call["url"]).netloc
            if host=="api.cloudflare.com":
                self.assertEqual(call["headers"].get("Authorization"),"Bearer "+ADMIN_TOKEN)
                self.assertNotEqual(call["headers"].get("Authorization"),"Bearer "+WORKER_TOKEN)
            elif host.endswith(".workers.dev"):
                self.assertNotEqual(call["headers"].get("Authorization"),"Bearer "+ADMIN_TOKEN)

    def test_subdomain_readiness_calls_precede_runtime(self):
        _,transport,_=self.rehearse()
        urls=[c["url"] for c in transport.calls]
        account_idx=next(i for i,u in enumerate(urls) if u.endswith("/workers/subdomain"))
        script_idx=next(i for i,u in enumerate(urls) if u.endswith("/subdomain") and "/workers/scripts/" in u)
        runtime_idx=next(i for i,u in enumerate(urls) if ".workers.dev/" in u)
        self.assertLess(account_idx,runtime_idx)
        self.assertLess(script_idx,runtime_idx)

    def test_duplicate_runtime_post_is_single_attempt_409(self):
        _,transport,_=self.rehearse()
        runtime_posts=[c for c in transport.calls if ".workers.dev/" in c["url"] and c["method"]=="POST"]
        self.assertEqual(len(runtime_posts),2)
        self.assertEqual(len(transport.receipts),1)

    def test_authorization_drift_fails_before_any_request(self):
        auth=authorization()
        transport=SyntheticCloudflareHTTPTransport()
        with self.assertRaisesRegex(CloudflareHTTPRequestShapeError,"AUTHORIZATION_HASH_MISMATCH"):
            rehearse_cloudflare_http_request_shapes(
                auth,scaffold_files(),transport,
                expected_authorization_qualification_sha256="f"*64,
                expected_current_main_sha=MAIN,
            )
        self.assertEqual(transport.calls,[])
        self.assertEqual(transport.consumed,set())

    def test_replay_and_real_or_subclass_transport_are_forbidden(self):
        result,transport,auth=self.rehearse()
        calls=list(transport.calls)
        with self.assertRaisesRegex(CloudflareHTTPRequestShapeError,"SINGLE_USE_ALREADY_CONSUMED"):
            rehearse_cloudflare_http_request_shapes(
                auth,scaffold_files(),transport,
                expected_authorization_qualification_sha256=canonical_digest(auth),
                expected_current_main_sha=MAIN,
            )
        self.assertEqual(transport.calls,calls)

        class SubclassTransport(SyntheticCloudflareHTTPTransport):
            pass
        with self.assertRaisesRegex(CloudflareHTTPRequestShapeError,"REAL_TRANSPORT_FORBIDDEN"):
            rehearse_cloudflare_http_request_shapes(
                auth,scaffold_files(),SubclassTransport(),
                expected_authorization_qualification_sha256=canonical_digest(auth),
                expected_current_main_sha=MAIN,
            )


if __name__=="__main__":
    unittest.main()

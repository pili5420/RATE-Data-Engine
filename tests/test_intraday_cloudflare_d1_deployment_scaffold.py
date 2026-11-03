"""Tests for Cloudflare Worker + D1 deployment scaffold."""
from __future__ import annotations

from copy import deepcopy
import unittest

from src.intraday_activation_candidate_review import canonical_digest
from src.intraday_cloudflare_d1_deployment_scaffold import (
    D1ScaffoldError,
    EXPECTED_FILES,
    build_cloudflare_d1_scaffold,
    validate_cloudflare_d1_scaffold,
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


class D1ScaffoldTests(unittest.TestCase):
    def build(self, value=None):
        q = value or qualification()
        return build_cloudflare_d1_scaffold(
            q,
            expected_candidate_qualification_sha256=canonical_digest(q),
        )

    def test_exact_scaffold_builds_and_self_reviews_without_deployment(self):
        result = self.build()
        self.assertEqual(result["validation_status"], "PASS")
        self.assertEqual(set(result["files"]), set(EXPECTED_FILES))
        self.assertFalse(result["deployment_ready"])
        self.assertEqual(result["real_cloudflare_requests"], 0)
        self.assertEqual(result["resources_created"], 0)

    def test_candidate_hash_is_external_trust_root(self):
        q = qualification()
        with self.assertRaisesRegex(D1ScaffoldError, "CANDIDATE_HASH_MISMATCH"):
            build_cloudflare_d1_scaffold(
                q,
                expected_candidate_qualification_sha256="f" * 64,
            )

    def test_worker_has_no_outbound_fetch_or_mutation_routes(self):
        result = self.build()
        worker = result["files"][EXPECTED_FILES[0]]
        self.assertNotIn("await fetch(", worker)
        self.assertNotIn("UPDATE rate_execution_receipts", worker)
        self.assertNotIn("DELETE FROM rate_execution_receipts", worker)
        self.assertNotIn("INSERT OR REPLACE", worker)
        self.assertIn("AMBIGUOUS_CREATE_CONFIRMED_BY_READBACK", worker)

    def test_worker_tamper_with_retry_or_update_fails_static_review(self):
        result = self.build()
        for injected in (
            "\nawait fetch('https://example.invalid');\n",
            "\nUPDATE rate_execution_receipts SET receipt_json='x';\n",
            "\nDELETE FROM rate_execution_receipts;\n",
            "\nINSERT OR REPLACE INTO rate_execution_receipts VALUES ('x');\n",
        ):
            files = deepcopy(result["files"])
            files[EXPECTED_FILES[0]] += injected
            with self.subTest(injected=injected), self.assertRaisesRegex(
                D1ScaffoldError, "WORKER_FORBIDDEN_BEHAVIOR"
            ):
                validate_cloudflare_d1_scaffold(files)

    def test_schema_has_primary_key_and_immutable_guards(self):
        result = self.build()
        schema = result["files"][EXPECTED_FILES[1]]
        self.assertIn("execution_id TEXT PRIMARY KEY NOT NULL", schema)
        self.assertIn("BEFORE UPDATE ON rate_execution_receipts", schema)
        self.assertIn("BEFORE DELETE ON rate_execution_receipts", schema)
        self.assertEqual(schema.count("IMMUTABLE_RECEIPT"), 2)

    def test_schema_tamper_removing_guard_fails(self):
        result = self.build()
        files = deepcopy(result["files"])
        files[EXPECTED_FILES[1]] = files[EXPECTED_FILES[1]].replace(
            "BEFORE DELETE ON rate_execution_receipts", "BEFORE SELECT ON rate_execution_receipts"
        )
        with self.assertRaisesRegex(D1ScaffoldError, "SCHEMA_IMMUTABILITY_INVALID"):
            validate_cloudflare_d1_scaffold(files)

    def test_wrangler_must_retain_database_placeholders(self):
        result = self.build()
        files = deepcopy(result["files"])
        files[EXPECTED_FILES[2]] = files[EXPECTED_FILES[2]].replace(
            "00000000-0000-0000-0000-000000000000",
            "11111111-1111-1111-1111-111111111111",
        )
        with self.assertRaisesRegex(D1ScaffoldError, "MUST_REMAIN_PLACEHOLDER"):
            validate_cloudflare_d1_scaffold(files)

    def test_secret_must_not_be_embedded_in_wrangler(self):
        result = self.build()
        files = deepcopy(result["files"])
        files[EXPECTED_FILES[2]] = files[EXPECTED_FILES[2]].replace(
            '"compatibility_date": "2026-11-03",',
            '"compatibility_date": "2026-11-03", "RATE_D1_RECEIPT_WORKER_TOKEN": "secret",',
        )
        with self.assertRaisesRegex(D1ScaffoldError, "SECRET_MUST_NOT_BE_CONFIG_FILE"):
            validate_cloudflare_d1_scaffold(files)

    def test_file_set_is_exact(self):
        result = self.build()
        files = deepcopy(result["files"])
        files["cloudflare/rate-execution-receipts/extra.txt"] = "x"
        with self.assertRaisesRegex(D1ScaffoldError, "FILE_SET_INVALID"):
            validate_cloudflare_d1_scaffold(files)

    def test_candidate_must_remain_unqualified_and_no_real_execution(self):
        q = qualification()
        q["provider_qualified"] = True
        with self.assertRaisesRegex(D1ScaffoldError, "CANDIDATE_NOT_ELIGIBLE"):
            self.build(q)


if __name__ == "__main__":
    unittest.main()

"""Tests for durable authority-store adapter semantics."""
from __future__ import annotations

from copy import deepcopy
import unittest

from src.intraday_activation_candidate_review import canonical_digest
from src.intraday_real_authority_store_adapter import (
    AuthorityStoreAdapterError,
    SyntheticAuthorityStoreAdapter,
    persist_receipt_via_adapter,
    validate_store_capabilities,
)

EXECUTION = "RATE-REAL-GIT-EXEC-2026-11-04-001"


def capabilities():
    return {
        "artifact": "RATE_INTRADAY_REAL_AUTHORITY_STORE_CAPABILITIES_V1",
        "durability": "EXTERNAL_PERSISTENT",
        "atomic_create_if_absent": True,
        "strong_read_after_write": True,
        "overwrite_allowed": False,
        "delete_allowed": False,
        "unbounded_listing_allowed": False,
        "transport": "HTTPS_TLS",
        "server_identity_verified": True,
        "credential_boundary": {
            "store": "GITHUB_ACTIONS_SECRET",
            "secret_name": "RATE_EXECUTION_RECEIPT_STORE_TOKEN",
            "secret_value_embedded": False,
        },
        "ambiguous_create_policy": "READ_SAME_EXECUTION_ID_DO_NOT_RETRY_CREATE",
        "receipt_key_scope": "EXACT_EXECUTION_ID",
        "receipt_format": "RATE_INTRADAY_REAL_GIT_EXECUTION_CONSUMPTION_RECEIPT_V1",
    }


def receipt():
    core = {
        "artifact": "RATE_INTRADAY_REAL_GIT_EXECUTION_CONSUMPTION_RECEIPT_V1",
        "state": "CONSUMED_BEFORE_GIT_MUTATION",
        "execution_id": EXECUTION,
        "authorization_qualification_sha256": "1" * 64,
        "base_main_sha": "2" * 40,
        "target_branch": "activation/rate-v11-intraday-test",
        "transaction_plan_sha256": "3" * 64,
        "candidate_manifest_sha256": "4" * 64,
        "provider_name": "Fugle",
        "single_use_consumed": True,
        "retry_allowed": False,
        "git_mutations_before_receipt": 0,
        "live_provider_requests": 0,
        "external_dependency_resolved": False,
        "registry_activation_allowed": False,
        "production_credit": 0,
        "cer081_credit": 0,
    }
    return {**core, "receipt_sha256": canonical_digest(core)}


class AuthorityStoreAdapterTests(unittest.TestCase):
    def test_exact_create_if_absent_and_readback_passes(self):
        adapter = SyntheticAuthorityStoreAdapter()
        result = persist_receipt_via_adapter(
            capabilities(), adapter, receipt(), execution_id=EXECUTION
        )
        self.assertEqual(result["validation_status"], "PASS")
        self.assertEqual(result["outcome"], "CREATED_AND_READBACK_VERIFIED")
        self.assertEqual(result["create_attempts"], 1)
        self.assertEqual(result["create_retries"], 0)
        self.assertEqual(adapter.records[EXECUTION], receipt())

    def test_duplicate_is_fail_closed_without_overwrite(self):
        adapter = SyntheticAuthorityStoreAdapter()
        persist_receipt_via_adapter(capabilities(), adapter, receipt(), execution_id=EXECUTION)
        before = deepcopy(adapter.records[EXECUTION])
        creates = adapter.create_attempts
        with self.assertRaisesRegex(AuthorityStoreAdapterError, "ALREADY_CONSUMED"):
            persist_receipt_via_adapter(
                capabilities(), adapter, receipt(), execution_id=EXECUTION
            )
        self.assertEqual(adapter.create_attempts, creates)
        self.assertEqual(adapter.records[EXECUTION], before)

    def test_ambiguous_after_create_is_resolved_by_read_without_create_retry(self):
        adapter = SyntheticAuthorityStoreAdapter(failure_mode="AMBIGUOUS_AFTER_CREATE")
        result = persist_receipt_via_adapter(
            capabilities(), adapter, receipt(), execution_id=EXECUTION
        )
        self.assertEqual(result["outcome"], "AMBIGUOUS_CREATE_CONFIRMED_BY_READBACK")
        self.assertEqual(adapter.create_attempts, 1)
        self.assertEqual(result["create_retries"], 0)
        self.assertEqual(adapter.records[EXECUTION], receipt())

    def test_failure_before_create_leaves_no_receipt(self):
        adapter = SyntheticAuthorityStoreAdapter(failure_mode="BEFORE_CREATE")
        with self.assertRaisesRegex(RuntimeError, "FAIL_BEFORE_CREATE"):
            persist_receipt_via_adapter(
                capabilities(), adapter, receipt(), execution_id=EXECUTION
            )
        self.assertEqual(adapter.create_attempts, 1)
        self.assertNotIn(EXECUTION, adapter.records)

    def test_capability_drift_fails_before_adapter_calls(self):
        for field, bad, reason in (
            ("atomic_create_if_absent", False, "DURABILITY_SEMANTICS_INVALID"),
            ("strong_read_after_write", False, "DURABILITY_SEMANTICS_INVALID"),
            ("overwrite_allowed", True, "MUTATION_BOUNDARY_INVALID"),
            ("delete_allowed", True, "MUTATION_BOUNDARY_INVALID"),
            ("ambiguous_create_policy", "RETRY_CREATE", "AMBIGUOUS_CREATE_POLICY_INVALID"),
        ):
            cap = capabilities()
            cap[field] = bad
            adapter = SyntheticAuthorityStoreAdapter()
            with self.subTest(field=field), self.assertRaisesRegex(
                AuthorityStoreAdapterError, reason
            ):
                persist_receipt_via_adapter(cap, adapter, receipt(), execution_id=EXECUTION)
            self.assertEqual(adapter.create_attempts, 0)
            self.assertEqual(adapter.read_attempts, 0)

    def test_transport_and_credential_boundaries_fail_before_adapter_calls(self):
        cases = []
        cap = capabilities()
        cap["server_identity_verified"] = False
        cases.append((cap, "TRANSPORT_INVALID"))

        cap = capabilities()
        cap["transport"] = "HTTP"
        cases.append((cap, "TRANSPORT_INVALID"))

        cap = capabilities()
        cap["credential_boundary"]["secret_value_embedded"] = True
        cases.append((cap, "CREDENTIAL_BOUNDARY_INVALID"))

        cap = capabilities()
        cap["credential_boundary"]["secret_name"] = ""
        cases.append((cap, "CREDENTIAL_BOUNDARY_INVALID"))

        for cap, reason in cases:
            adapter = SyntheticAuthorityStoreAdapter()
            with self.subTest(reason=reason), self.assertRaisesRegex(
                AuthorityStoreAdapterError, reason
            ):
                persist_receipt_via_adapter(
                    cap, adapter, receipt(), execution_id=EXECUTION
                )
            self.assertEqual(adapter.create_attempts, 0)
            self.assertEqual(adapter.read_attempts, 0)

    def test_existing_different_receipt_is_conflict_not_overwrite(self):
        adapter = SyntheticAuthorityStoreAdapter()
        other = receipt()
        other["provider_name"] = "Other"
        core = {k: v for k, v in other.items() if k != "receipt_sha256"}
        other["receipt_sha256"] = canonical_digest(core)
        adapter.records[EXECUTION] = other
        with self.assertRaisesRegex(AuthorityStoreAdapterError, "EXISTING_RECEIPT_CONFLICT"):
            persist_receipt_via_adapter(
                capabilities(), adapter, receipt(), execution_id=EXECUTION
            )
        self.assertEqual(adapter.create_attempts, 0)
        self.assertEqual(adapter.records[EXECUTION], other)

    def test_receipt_tamper_fails_before_adapter_calls(self):
        value = receipt()
        value["provider_name"] = "Other"
        adapter = SyntheticAuthorityStoreAdapter()
        with self.assertRaisesRegex(AuthorityStoreAdapterError, "SELF_HASH_MISMATCH"):
            persist_receipt_via_adapter(
                capabilities(), adapter, value, execution_id=EXECUTION
            )
        self.assertEqual(adapter.create_attempts, 0)

    def test_invalid_execution_id_fails_before_adapter_calls(self):
        for value in ("BAD..ID", "TRAILING.", "reserved.lock", ""):
            adapter = SyntheticAuthorityStoreAdapter()
            with self.subTest(value=value), self.assertRaisesRegex(
                AuthorityStoreAdapterError, "EXECUTION_ID_INVALID"
            ):
                persist_receipt_via_adapter(
                    capabilities(), adapter, receipt(), execution_id=value
                )
            self.assertEqual(adapter.create_attempts, 0)

    def test_real_or_subclass_adapter_forbidden_in_engineering(self):
        class SubclassAdapter(SyntheticAuthorityStoreAdapter):
            pass
        with self.assertRaisesRegex(AuthorityStoreAdapterError, "REAL_ADAPTER_FORBIDDEN"):
            persist_receipt_via_adapter(
                capabilities(), SubclassAdapter(), receipt(), execution_id=EXECUTION
            )

    def test_capability_validator_returns_copy(self):
        source = capabilities()
        validated = validate_store_capabilities(source)
        self.assertEqual(validated, source)
        validated["overwrite_allowed"] = True
        self.assertFalse(source["overwrite_allowed"])


if __name__ == "__main__":
    unittest.main()

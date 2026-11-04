"""Tests for durable-receipt-before-Git orchestration."""
from __future__ import annotations

from unittest.mock import patch
import unittest

from src.intraday_activation_apply_authorization import EXPECTED_PATHS
from src.intraday_activation_apply_transaction_plan import build_activation_apply_transaction_plan
from src.intraday_activation_candidate_materialization import candidate_manifest_sha256
from src.intraday_activation_candidate_review import canonical_digest
from src.intraday_durable_receipt_git_orchestration import (
    DurableReceiptGitOrchestrationError,
    rehearse_durable_receipt_then_git,
)
from src.intraday_git_transaction_rehearsal import SyntheticGitBackend
from src.intraday_real_git_execution_authorization import EXPECTED_BUDGET
from src.intraday_real_git_execution_fence import (
    ExecutionFenceError,
    SyntheticWriteOnceReceiptStore,
)

MAIN = "1" * 40
PROVIDER = "Fugle"
DECISION = "CC-ACTIVATION-APPLY-2026-11-04"
EXECUTION_ID = "RATE-REAL-GIT-EXEC-2026-11-04-001"


def files():
    return {
        path: f"candidate-{index}-{path}\n"
        for index, path in enumerate(EXPECTED_PATHS)
    }


def apply_auth_qualification(manifest):
    return {
        "artifact": "RATE_INTRADAY_ACTIVATION_APPLY_AUTHORIZATION_QUALIFICATION_V1",
        "validation_status": "PASS",
        "control_center_decision_id": DECISION,
        "authorization_sha256": "2" * 64,
        "final_main_readiness_sha256": "3" * 64,
        "current_main_sha": MAIN,
        "candidate_manifest_sha256": manifest,
        "provider_name": PROVIDER,
        "single_use": True,
        "automatic_retry_allowed": False,
        "fallback_allowed": False,
        "allowed_paths": list(EXPECTED_PATHS),
        "authorization_valid": True,
        "apply_executed": False,
        "activation_execution_allowed_by_this_validator": False,
        "external_dependency_resolved": False,
        "registry_activation_allowed": False,
        "repository_writes": 0,
        "live_provider_requests": 0,
        "production_credit": 0,
        "cer081_credit": 0,
        "next_gate": "SEPARATE_SINGLE_USE_ACTIVATION_APPLY_EXECUTOR",
    }


def transaction_plan(candidate):
    manifest = candidate_manifest_sha256(candidate)
    q = apply_auth_qualification(manifest)
    return build_activation_apply_transaction_plan(
        q,
        candidate,
        expected_authorization_qualification_sha256=canonical_digest(q),
        expected_current_main_sha=MAIN,
        expected_candidate_manifest_sha256=manifest,
        expected_control_center_decision_id=DECISION,
        expected_provider_name=PROVIDER,
    )


def real_git_auth(plan):
    return {
        "artifact": "RATE_INTRADAY_REAL_GIT_TRANSACTION_EXECUTION_AUTHORIZATION_QUALIFICATION_V1",
        "validation_status": "PASS",
        "control_center_decision_id": DECISION,
        "authorization_sha256": "4" * 64,
        "transaction_plan_sha256": canonical_digest(plan),
        "rehearsal_sha256": "5" * 64,
        "base_main_sha": MAIN,
        "candidate_manifest_sha256": plan["candidate_manifest_sha256"],
        "target_branch": plan["target_branch"],
        "target_base": "main",
        "provider_name": PROVIDER,
        "operation_budget": dict(EXPECTED_BUDGET),
        "single_use": True,
        "retry_allowed": False,
        "draft_pull_request_required": True,
        "direct_main_update_allowed": False,
        "merge_allowed": False,
        "authorization_valid": True,
        "execution_performed": False,
        "real_git_operations": 0,
        "live_provider_requests": 0,
        "external_dependency_resolved": False,
        "registry_activation_allowed": False,
        "production_credit": 0,
        "cer081_credit": 0,
        "next_gate": "SEPARATE_REAL_GIT_TRANSACTION_EXECUTOR",
    }


def readiness(auth):
    return {
        "artifact": "RATE_REAL_GIT_EXECUTION_WITH_ACCEPTED_AUTHORITY_STORE_READINESS_V1",
        "validation_status": "PASS",
        "current_main_sha": MAIN,
        "target_branch": auth["target_branch"],
        "intraday_provider_name": PROVIDER,
        "authority_store_provider": "CLOUDFLARE_WORKERS_D1",
        "authority_store_role": "REAL_GIT_EXECUTION_CONSUMPTION_RECEIPT_STORE",
        "authority_store_provider_accepted": True,
        "authority_store_provider_qualified": True,
        "operation_budget": dict(EXPECTED_BUDGET),
        "consumption_receipt_artifact":
            "RATE_INTRADAY_REAL_GIT_EXECUTION_CONSUMPTION_RECEIPT_V1",
        "consumption_receipt_state": "CONSUMED_BEFORE_GIT_MUTATION",
        "persist_receipt_before_first_git_mutation": True,
        "write_once_receipt_required": True,
        "receipt_retry_after_consumption_allowed": False,
        "readiness_only": True,
        "real_git_transaction_execution_allowed": False,
        "receipt_consumed": False,
        "real_git_operations": 0,
        "live_provider_requests": 0,
        "external_intraday_dependency_resolved": False,
        "production_credit": 0,
        "cer081_credit": 0,
        "next_gate":
            "SEPARATE_REAL_GIT_EXECUTOR_WITH_DURABLE_RECEIPT_AUTHORIZATION",
    }


def fixture():
    candidate = files()
    plan = transaction_plan(candidate)
    auth = real_git_auth(plan)
    ready = readiness(auth)
    return ready, auth, plan, candidate


class DurableReceiptGitOrchestrationTests(unittest.TestCase):
    def run_flow(self, store=None, backend=None, **overrides):
        ready, auth, plan, candidate = fixture()
        store = store or SyntheticWriteOnceReceiptStore()
        backend = backend or SyntheticGitBackend(main_sha=MAIN)
        result = rehearse_durable_receipt_then_git(
            ready,
            auth,
            plan,
            candidate,
            store,
            backend,
            execution_id=EXECUTION_ID,
            expected_readiness_sha256=overrides.get(
                "readiness_hash", canonical_digest(ready)
            ),
            expected_real_git_authorization_sha256=overrides.get(
                "auth_hash", canonical_digest(auth)
            ),
            expected_transaction_plan_sha256=overrides.get(
                "plan_hash", canonical_digest(plan)
            ),
            expected_candidate_manifest_sha256=overrides.get(
                "manifest_hash", candidate_manifest_sha256(candidate)
            ),
        )
        return result, store, backend, ready, auth, plan, candidate

    def test_receipt_is_persisted_before_successful_synthetic_git(self):
        result, store, backend, _, _, _, _ = self.run_flow()
        self.assertEqual(result["validation_status"], "PASS")
        self.assertTrue(result["receipt_persisted_before_git"])
        self.assertEqual(result["git_mutations_before_receipt"], 0)
        self.assertEqual(result["receipt_state"], "CONSUMED_BEFORE_GIT_MUTATION")
        self.assertEqual(store.write_attempts, 1)
        self.assertEqual(result["synthetic_blob_count"], 9)
        self.assertTrue(result["synthetic_branch_ref_created_last"])
        self.assertEqual(backend.refs["main"], MAIN)
        self.assertEqual(result["real_git_operations"], 0)

    def test_receipt_exists_before_downstream_git_function_is_called(self):
        ready, auth, plan, candidate = fixture()
        store = SyntheticWriteOnceReceiptStore()
        backend = SyntheticGitBackend(main_sha=MAIN)

        def downstream(*args, **kwargs):
            persisted = store.read(EXECUTION_ID)
            self.assertIsNotNone(persisted)
            self.assertEqual(persisted["state"], "CONSUMED_BEFORE_GIT_MUTATION")
            self.assertEqual(persisted["git_mutations_before_receipt"], 0)
            return {
                "validation_status": "PASS",
                "synthetic_branch": plan["target_branch"],
                "blob_count": 9,
                "main_ref_unchanged": True,
                "branch_ref_created_last": True,
                "synthetic_tree_sha": "a" * 40,
                "synthetic_commit_sha": "b" * 40,
            }

        with patch(
            "src.intraday_durable_receipt_git_orchestration."
            "rehearse_activation_git_transaction",
            side_effect=downstream,
        ) as called:
            result = rehearse_durable_receipt_then_git(
                ready, auth, plan, candidate, store, backend,
                execution_id=EXECUTION_ID,
                expected_readiness_sha256=canonical_digest(ready),
                expected_real_git_authorization_sha256=canonical_digest(auth),
                expected_transaction_plan_sha256=canonical_digest(plan),
                expected_candidate_manifest_sha256=candidate_manifest_sha256(candidate),
            )
        called.assert_called_once()
        self.assertTrue(result["receipt_persisted_before_git"])

    def test_receipt_write_failure_blocks_all_git_calls(self):
        ready, auth, plan, candidate = fixture()
        store = SyntheticWriteOnceReceiptStore(fail_write=True)
        backend = SyntheticGitBackend(main_sha=MAIN)
        with patch(
            "src.intraday_durable_receipt_git_orchestration."
            "rehearse_activation_git_transaction",
            side_effect=AssertionError("GIT_STARTED_WITHOUT_RECEIPT"),
        ) as downstream:
            with self.assertRaisesRegex(RuntimeError, "RECEIPT_STORE_WRITE_FAILED"):
                rehearse_durable_receipt_then_git(
                    ready, auth, plan, candidate, store, backend,
                    execution_id=EXECUTION_ID,
                    expected_readiness_sha256=canonical_digest(ready),
                    expected_real_git_authorization_sha256=canonical_digest(auth),
                    expected_transaction_plan_sha256=canonical_digest(plan),
                    expected_candidate_manifest_sha256=candidate_manifest_sha256(candidate),
                )
        downstream.assert_not_called()
        self.assertEqual(backend.calls, [])

    def test_git_failure_leaves_durable_receipt_and_reentry_is_blocked_before_new_git_calls(self):
        ready, auth, plan, candidate = fixture()
        store = SyntheticWriteOnceReceiptStore()
        fail_path = EXPECTED_PATHS[3]
        backend = SyntheticGitBackend(
            main_sha=MAIN,
            fail_at="blob:" + fail_path,
        )
        with self.assertRaisesRegex(RuntimeError, "SYNTHETIC_GIT_FAIL"):
            rehearse_durable_receipt_then_git(
                ready, auth, plan, candidate, store, backend,
                execution_id=EXECUTION_ID,
                expected_readiness_sha256=canonical_digest(ready),
                expected_real_git_authorization_sha256=canonical_digest(auth),
                expected_transaction_plan_sha256=canonical_digest(plan),
                expected_candidate_manifest_sha256=candidate_manifest_sha256(candidate),
            )
        persisted = store.read(EXECUTION_ID)
        self.assertIsNotNone(persisted)
        calls_before = list(backend.calls)
        with self.assertRaisesRegex(ExecutionFenceError, "ALREADY_CONSUMED"):
            rehearse_durable_receipt_then_git(
                ready, auth, plan, candidate, store, backend,
                execution_id=EXECUTION_ID,
                expected_readiness_sha256=canonical_digest(ready),
                expected_real_git_authorization_sha256=canonical_digest(auth),
                expected_transaction_plan_sha256=canonical_digest(plan),
                expected_candidate_manifest_sha256=candidate_manifest_sha256(candidate),
            )
        self.assertEqual(backend.calls, calls_before)
        self.assertEqual(store.read(EXECUTION_ID), persisted)

    def test_ephemeral_backend_consumed_without_durable_receipt_fails_before_receipt_write(self):
        ready, auth, plan, candidate = fixture()
        store = SyntheticWriteOnceReceiptStore()
        backend = SyntheticGitBackend(main_sha=MAIN)
        backend.consumed_tokens.add(canonical_digest(plan))
        with self.assertRaisesRegex(
            DurableReceiptGitOrchestrationError,
            "BACKEND_PLAN_ALREADY_CONSUMED",
        ):
            rehearse_durable_receipt_then_git(
                ready, auth, plan, candidate, store, backend,
                execution_id=EXECUTION_ID,
                expected_readiness_sha256=canonical_digest(ready),
                expected_real_git_authorization_sha256=canonical_digest(auth),
                expected_transaction_plan_sha256=canonical_digest(plan),
                expected_candidate_manifest_sha256=candidate_manifest_sha256(candidate),
            )
        self.assertEqual(store.write_attempts, 0)
        self.assertIsNone(store.read(EXECUTION_ID))
        self.assertEqual(backend.calls, [])

    def test_candidate_drift_fails_before_receipt_consumption(self):
        ready, auth, plan, candidate = fixture()
        candidate = dict(candidate)
        candidate[EXPECTED_PATHS[0]] += "tamper\n"
        store = SyntheticWriteOnceReceiptStore()
        backend = SyntheticGitBackend(main_sha=MAIN)
        with self.assertRaisesRegex(
            DurableReceiptGitOrchestrationError,
            "CANDIDATE_MANIFEST_HASH_MISMATCH",
        ):
            rehearse_durable_receipt_then_git(
                ready, auth, plan, candidate, store, backend,
                execution_id=EXECUTION_ID,
                expected_readiness_sha256=canonical_digest(ready),
                expected_real_git_authorization_sha256=canonical_digest(auth),
                expected_transaction_plan_sha256=canonical_digest(plan),
                expected_candidate_manifest_sha256=plan["candidate_manifest_sha256"],
            )
        self.assertEqual(store.write_attempts, 0)
        self.assertEqual(backend.calls, [])

    def test_branch_or_main_drift_fails_before_receipt_consumption(self):
        ready, auth, plan, candidate = fixture()
        for backend in (
            SyntheticGitBackend(main_sha="f" * 40),
            SyntheticGitBackend(main_sha=MAIN),
        ):
            store = SyntheticWriteOnceReceiptStore()
            if backend.refs["main"] == MAIN:
                backend.refs[plan["target_branch"]] = "e" * 40
                reason = "TARGET_BRANCH_ALREADY_EXISTS"
            else:
                reason = "BACKEND_MAIN_DRIFT"
            with self.subTest(reason=reason), self.assertRaisesRegex(
                DurableReceiptGitOrchestrationError, reason
            ):
                rehearse_durable_receipt_then_git(
                    ready, auth, plan, candidate, store, backend,
                    execution_id=EXECUTION_ID,
                    expected_readiness_sha256=canonical_digest(ready),
                    expected_real_git_authorization_sha256=canonical_digest(auth),
                    expected_transaction_plan_sha256=canonical_digest(plan),
                    expected_candidate_manifest_sha256=candidate_manifest_sha256(candidate),
                )
            self.assertEqual(store.write_attempts, 0)

    def test_readiness_and_authorization_hashes_are_external_trust_roots(self):
        for key, value, reason in (
            ("readiness_hash", "f" * 64, "READINESS_HASH_MISMATCH"),
            ("auth_hash", "e" * 64, "AUTHORIZATION_HASH_MISMATCH"),
            ("plan_hash", "d" * 64, "PLAN_HASH_MISMATCH"),
        ):
            store = SyntheticWriteOnceReceiptStore()
            backend = SyntheticGitBackend(main_sha=MAIN)
            with self.subTest(key=key), self.assertRaisesRegex(
                DurableReceiptGitOrchestrationError, reason
            ):
                self.run_flow(store=store, backend=backend, **{key: value})
            self.assertEqual(store.write_attempts, 0)
            self.assertEqual(backend.calls, [])


if __name__ == "__main__":
    unittest.main()

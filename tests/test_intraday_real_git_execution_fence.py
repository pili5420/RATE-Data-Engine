"""Tests for durable single-use real-Git execution consumption fencing."""
from __future__ import annotations

from copy import deepcopy
import unittest

from src.intraday_activation_candidate_review import canonical_digest
from src.intraday_real_git_execution_authorization import EXPECTED_BUDGET
from src.intraday_real_git_execution_fence import (
    ExecutionFenceError,
    SyntheticWriteOnceReceiptStore,
    consume_execution_fence,
    validate_consumed_execution_fence,
)

MAIN = "1" * 40
BRANCH = "activation/rate-v11-intraday-cc-real-git-exec-2026-11-04"
EXECUTION = "RATE-REAL-GIT-EXEC-2026-11-04-001"


def qualification():
    return {
        "artifact": "RATE_INTRADAY_REAL_GIT_TRANSACTION_EXECUTION_AUTHORIZATION_QUALIFICATION_V1",
        "validation_status": "PASS",
        "control_center_decision_id": "CC-REAL-GIT-EXEC-2026-11-04",
        "authorization_sha256": "2" * 64,
        "transaction_plan_sha256": "3" * 64,
        "rehearsal_sha256": "4" * 64,
        "base_main_sha": MAIN,
        "candidate_manifest_sha256": "5" * 64,
        "target_branch": BRANCH,
        "target_base": "main",
        "provider_name": "Fugle",
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


class ExecutionFenceTests(unittest.TestCase):
    def consume(self, q=None, store=None, execution_id=EXECUTION):
        q = q or qualification()
        store = store or SyntheticWriteOnceReceiptStore()
        receipt = consume_execution_fence(
            q,
            store,
            execution_id=execution_id,
            expected_qualification_sha256=canonical_digest(q),
            expected_current_main_sha=MAIN,
            expected_target_branch=BRANCH,
        )
        return receipt, store, q

    def test_exact_receipt_is_persisted_before_any_git_mutation(self):
        receipt, store, q = self.consume()
        self.assertEqual(receipt["state"], "CONSUMED_BEFORE_GIT_MUTATION")
        self.assertTrue(receipt["single_use_consumed"])
        self.assertFalse(receipt["retry_allowed"])
        self.assertEqual(receipt["git_mutations_before_receipt"], 0)
        self.assertEqual(store.write_attempts, 1)
        validated = validate_consumed_execution_fence(
            store,
            execution_id=EXECUTION,
            expected_receipt_sha256=receipt["receipt_sha256"],
            expected_qualification_sha256=canonical_digest(q),
            expected_current_main_sha=MAIN,
            expected_target_branch=BRANCH,
        )
        self.assertEqual(validated, receipt)

    def test_replay_fails_without_second_write_attempt(self):
        receipt, store, q = self.consume()
        attempts = store.write_attempts
        with self.assertRaisesRegex(ExecutionFenceError, "ALREADY_CONSUMED"):
            consume_execution_fence(
                q,
                store,
                execution_id=EXECUTION,
                expected_qualification_sha256=canonical_digest(q),
                expected_current_main_sha=MAIN,
                expected_target_branch=BRANCH,
            )
        self.assertEqual(store.write_attempts, attempts)
        self.assertEqual(store.read(EXECUTION), receipt)

    def test_qualification_drift_fails_before_store_write(self):
        q = qualification()
        store = SyntheticWriteOnceReceiptStore()
        with self.assertRaisesRegex(ExecutionFenceError, "QUALIFICATION_HASH_MISMATCH"):
            consume_execution_fence(
                q,
                store,
                execution_id=EXECUTION,
                expected_qualification_sha256="f" * 64,
                expected_current_main_sha=MAIN,
                expected_target_branch=BRANCH,
            )
        self.assertEqual(store.write_attempts, 0)
        self.assertIsNone(store.read(EXECUTION))

    def test_main_and_branch_drift_fail_before_store_write(self):
        q = qualification()
        for kwargs, reason in (
            ({"expected_current_main_sha": "f" * 40}, "MAIN_BINDING_MISMATCH"),
            ({"expected_target_branch": BRANCH + "-other"}, "BRANCH_BINDING_MISMATCH"),
        ):
            store = SyntheticWriteOnceReceiptStore()
            params = {
                "execution_id": EXECUTION,
                "expected_qualification_sha256": canonical_digest(q),
                "expected_current_main_sha": MAIN,
                "expected_target_branch": BRANCH,
                **kwargs,
            }
            with self.subTest(kwargs=kwargs), self.assertRaisesRegex(
                ExecutionFenceError, reason
            ):
                consume_execution_fence(q, store, **params)
            self.assertEqual(store.write_attempts, 0)

    def test_store_write_failure_leaves_no_false_consumed_receipt(self):
        q = qualification()
        store = SyntheticWriteOnceReceiptStore(fail_write=True)
        with self.assertRaisesRegex(RuntimeError, "STORE_WRITE_FAILED"):
            consume_execution_fence(
                q,
                store,
                execution_id=EXECUTION,
                expected_qualification_sha256=canonical_digest(q),
                expected_current_main_sha=MAIN,
                expected_target_branch=BRANCH,
            )
        self.assertEqual(store.write_attempts, 1)
        self.assertIsNone(store.read(EXECUTION))

    def test_already_consumed_receipt_survives_process_style_reentry(self):
        receipt, store, q = self.consume()
        validated = validate_consumed_execution_fence(
            store,
            execution_id=EXECUTION,
            expected_receipt_sha256=receipt["receipt_sha256"],
            expected_qualification_sha256=canonical_digest(q),
            expected_current_main_sha=MAIN,
            expected_target_branch=BRANCH,
        )
        self.assertEqual(validated["state"], "CONSUMED_BEFORE_GIT_MUTATION")
        with self.assertRaisesRegex(ExecutionFenceError, "ALREADY_CONSUMED"):
            consume_execution_fence(
                deepcopy(q),
                store,
                execution_id=EXECUTION,
                expected_qualification_sha256=canonical_digest(q),
                expected_current_main_sha=MAIN,
                expected_target_branch=BRANCH,
            )

    def test_receipt_tamper_is_detected(self):
        receipt, store, q = self.consume()
        store.records[EXECUTION]["provider_name"] = "Other"
        with self.assertRaisesRegex(ExecutionFenceError, "SELF_HASH_MISMATCH"):
            validate_consumed_execution_fence(
                store,
                execution_id=EXECUTION,
                expected_receipt_sha256=receipt["receipt_sha256"],
                expected_qualification_sha256=canonical_digest(q),
                expected_current_main_sha=MAIN,
                expected_target_branch=BRANCH,
            )

    def test_invalid_execution_ids_fail_before_store_write(self):
        q = qualification()
        for execution_id in ("BAD..ID", "TRAILING.", "reserved.lock", ""):
            store = SyntheticWriteOnceReceiptStore()
            with self.subTest(execution_id=execution_id), self.assertRaisesRegex(
                ExecutionFenceError, "EXECUTION_ID_INVALID"
            ):
                consume_execution_fence(
                    q,
                    store,
                    execution_id=execution_id,
                    expected_qualification_sha256=canonical_digest(q),
                    expected_current_main_sha=MAIN,
                    expected_target_branch=BRANCH,
                )
            self.assertEqual(store.write_attempts, 0)

    def test_real_or_subclass_store_is_forbidden_in_engineering(self):
        class SubclassStore(SyntheticWriteOnceReceiptStore):
            pass
        q = qualification()
        with self.assertRaisesRegex(ExecutionFenceError, "REAL_STORE_FORBIDDEN"):
            consume_execution_fence(
                q,
                SubclassStore(),
                execution_id=EXECUTION,
                expected_qualification_sha256=canonical_digest(q),
                expected_current_main_sha=MAIN,
                expected_target_branch=BRANCH,
            )


if __name__ == "__main__":
    unittest.main()

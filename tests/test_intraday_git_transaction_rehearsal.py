"""Synthetic Git transaction executor rehearsal tests."""
from __future__ import annotations

import unittest

from src.intraday_activation_apply_authorization import EXPECTED_PATHS
from src.intraday_activation_apply_transaction_plan import (
    build_activation_apply_transaction_plan,
)
from src.intraday_activation_candidate_materialization import candidate_manifest_sha256
from src.intraday_activation_candidate_review import canonical_digest
from src.intraday_git_transaction_rehearsal import (
    GitTransactionRehearsalError,
    SyntheticGitBackend,
    rehearse_activation_git_transaction,
)
from src.intraday_activation_readiness import repo_preimage_hashes

MAIN = "1" * 40
PROVIDER = "Fugle"
DECISION = "CC-ACTIVATION-APPLY-2026-11-04"


def files():
    return {path: f"candidate-{index}-{path}\n" for index, path in enumerate(EXPECTED_PATHS)}


def authorization_qualification(manifest):
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


def plan(candidate):
    manifest = candidate_manifest_sha256(candidate)
    q = authorization_qualification(manifest)
    return build_activation_apply_transaction_plan(
        q,
        candidate,
        expected_authorization_qualification_sha256=canonical_digest(q),
        expected_current_main_sha=MAIN,
        expected_candidate_manifest_sha256=manifest,
        expected_control_center_decision_id=DECISION,
        expected_provider_name=PROVIDER,
    )


class GitTransactionRehearsalTests(unittest.TestCase):
    def run_rehearsal(self, backend=None):
        candidate = files()
        p = plan(candidate)
        backend = backend or SyntheticGitBackend(main_sha=MAIN)
        result = rehearse_activation_git_transaction(
            p,
            candidate,
            backend,
            expected_transaction_plan_sha256=canonical_digest(p),
            expected_base_main_sha=MAIN,
            expected_candidate_manifest_sha256=candidate_manifest_sha256(candidate),
        )
        return result, backend, p, candidate

    def test_success_sequence_creates_branch_last_and_never_mutates_main(self):
        result, backend, _, _ = self.run_rehearsal()
        self.assertEqual(result["validation_status"], "PASS")
        self.assertEqual(result["blob_count"], 9)
        self.assertTrue(result["single_use_consumed"])
        self.assertFalse(result["retry_allowed"])
        self.assertTrue(result["main_ref_unchanged"])
        self.assertTrue(result["branch_ref_created_last"])
        self.assertEqual(backend.refs["main"], MAIN)
        self.assertEqual(result["real_git_objects_created"], 0)
        self.assertEqual(result["real_repository_writes"], 0)
        self.assertFalse(result["merge_performed"])

    def test_replay_is_blocked_before_new_git_mutations(self):
        result, backend, p, candidate = self.run_rehearsal()
        calls_before = list(backend.calls)
        with self.assertRaisesRegex(
            GitTransactionRehearsalError, "SINGLE_USE_ALREADY_CONSUMED"
        ):
            rehearse_activation_git_transaction(
                p, candidate, backend,
                expected_transaction_plan_sha256=canonical_digest(p),
                expected_base_main_sha=MAIN,
                expected_candidate_manifest_sha256=candidate_manifest_sha256(candidate),
            )
        self.assertEqual(
            backend.calls[len(calls_before)],
            "consume:" + canonical_digest(p),
        )
        self.assertEqual(
            [c for c in backend.calls[len(calls_before)+1:] if c.startswith("blob:")],
            [],
        )

    def test_blob_failure_consumes_single_use_and_creates_no_branch(self):
        candidate = files()
        p = plan(candidate)
        fail_path = EXPECTED_PATHS[4]
        backend = SyntheticGitBackend(main_sha=MAIN, fail_at="blob:" + fail_path)
        with self.assertRaisesRegex(RuntimeError, "SYNTHETIC_GIT_FAIL"):
            rehearse_activation_git_transaction(
                p, candidate, backend,
                expected_transaction_plan_sha256=canonical_digest(p),
                expected_base_main_sha=MAIN,
                expected_candidate_manifest_sha256=candidate_manifest_sha256(candidate),
            )
        self.assertIn(canonical_digest(p), backend.consumed_tokens)
        self.assertEqual(backend.refs, {"main": MAIN})
        with self.assertRaisesRegex(
            GitTransactionRehearsalError, "SINGLE_USE_ALREADY_CONSUMED"
        ):
            rehearse_activation_git_transaction(
                p, candidate, backend,
                expected_transaction_plan_sha256=canonical_digest(p),
                expected_base_main_sha=MAIN,
                expected_candidate_manifest_sha256=candidate_manifest_sha256(candidate),
            )

    def test_tree_commit_and_ref_failures_never_mutate_main(self):
        for point in ("tree", "commit", "ref"):
            candidate = files()
            p = plan(candidate)
            backend = SyntheticGitBackend(main_sha=MAIN, fail_at=point)
            with self.subTest(point=point), self.assertRaisesRegex(
                RuntimeError, "SYNTHETIC_GIT_FAIL"
            ):
                rehearse_activation_git_transaction(
                    p, candidate, backend,
                    expected_transaction_plan_sha256=canonical_digest(p),
                    expected_base_main_sha=MAIN,
                    expected_candidate_manifest_sha256=candidate_manifest_sha256(candidate),
                )
            self.assertEqual(backend.refs.get("main"), MAIN)
            self.assertNotIn(p["target_branch"], backend.refs)
            self.assertIn(canonical_digest(p), backend.consumed_tokens)

    def test_real_or_subclass_backend_is_rejected(self):
        class FakeRealBackend(SyntheticGitBackend):
            pass
        candidate = files()
        p = plan(candidate)
        backend = FakeRealBackend(main_sha=MAIN)
        with self.assertRaisesRegex(
            GitTransactionRehearsalError, "REAL_BACKEND_FORBIDDEN"
        ):
            rehearse_activation_git_transaction(
                p, candidate, backend,
                expected_transaction_plan_sha256=canonical_digest(p),
                expected_base_main_sha=MAIN,
                expected_candidate_manifest_sha256=candidate_manifest_sha256(candidate),
            )

    def test_main_or_candidate_drift_fails_before_token_consumption(self):
        candidate = files()
        p = plan(candidate)
        backend = SyntheticGitBackend(main_sha="f" * 40)
        with self.assertRaisesRegex(
            GitTransactionRehearsalError, "MAIN_BINDING_MISMATCH"
        ):
            rehearse_activation_git_transaction(
                p, candidate, backend,
                expected_transaction_plan_sha256=canonical_digest(p),
                expected_base_main_sha=MAIN,
                expected_candidate_manifest_sha256=candidate_manifest_sha256(candidate),
            )
        self.assertEqual(backend.consumed_tokens, set())

        backend = SyntheticGitBackend(main_sha=MAIN)
        tampered = dict(candidate)
        tampered[EXPECTED_PATHS[0]] += "tamper\n"
        with self.assertRaisesRegex(
            GitTransactionRehearsalError, "CANDIDATE_MANIFEST_HASH_MISMATCH"
        ):
            rehearse_activation_git_transaction(
                p, tampered, backend,
                expected_transaction_plan_sha256=canonical_digest(p),
                expected_base_main_sha=MAIN,
                expected_candidate_manifest_sha256=candidate_manifest_sha256(candidate),
            )
        self.assertEqual(backend.consumed_tokens, set())


if __name__ == "__main__":
    unittest.main()

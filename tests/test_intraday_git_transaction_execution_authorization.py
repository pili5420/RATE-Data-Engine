"""Tests for explicit real Git transaction execution authorization qualification."""
from __future__ import annotations

import unittest

from src.intraday_activation_apply_authorization import EXPECTED_PATHS
from src.intraday_activation_candidate_review import canonical_digest
from src.intraday_git_transaction_execution_authorization import (
    ALLOWED_OPERATIONS,
    RealGitExecutionAuthorizationError,
    validate_real_git_transaction_execution_authorization,
)

MAIN = "1" * 40
MANIFEST = "4" * 64
DECISION = "CC-REAL-GIT-EXEC-2026-11-04"
PROVIDER = "Fugle"
BRANCH = "activation/rate-v11-intraday-" + DECISION.lower()


def transaction_plan():
    files = {
        path: {
            "mode": "100644",
            "content_sha256": "5" * 64,
            "git_blob_sha1": "6" * 40,
            "operation": "REPLACE_EXISTING",
            "base_sha256": "7" * 64,
        }
        for path in EXPECTED_PATHS
    }
    return {
        "artifact": "RATE_INTRADAY_ACTIVATION_APPLY_TRANSACTION_PLAN_V1",
        "status": "TRANSACTION_PLAN_ONLY",
        "control_center_decision_id": DECISION,
        "authorization_qualification_sha256": "8" * 64,
        "base_main_sha": MAIN,
        "candidate_manifest_sha256": MANIFEST,
        "provider_name": PROVIDER,
        "single_use": True,
        "automatic_retry_allowed": False,
        "fallback_allowed": False,
        "target_branch": BRANCH,
        "target_base": "main",
        "merge_allowed_by_plan": False,
        "direct_main_update_allowed": False,
        "files": files,
        "existing_file_preimage_sha256": {},
        "new_runtime_file_absence": {},
        "apply_executed": False,
        "repository_writes": 0,
        "live_provider_requests": 0,
        "external_dependency_resolved": False,
        "registry_activation_allowed": False,
        "production_credit": 0,
        "cer081_credit": 0,
        "transaction_plan_sha256": "9" * 64,
        "next_gate": "SEPARATE_SINGLE_USE_GIT_TRANSACTION_EXECUTOR",
    }


def rehearsal(plan_hash):
    return {
        "artifact": "RATE_INTRADAY_ACTIVATION_GIT_TRANSACTION_REHEARSAL_V1",
        "validation_status": "PASS",
        "transport": "SYNTHETIC_IN_MEMORY_ONLY",
        "transaction_plan_sha256": plan_hash,
        "base_main_sha": MAIN,
        "candidate_manifest_sha256": MANIFEST,
        "synthetic_tree_sha": "a" * 40,
        "synthetic_commit_sha": "b" * 40,
        "synthetic_branch": BRANCH,
        "blob_count": 9,
        "single_use_consumed": True,
        "retry_allowed": False,
        "main_ref_unchanged": True,
        "branch_ref_created_last": True,
        "real_git_objects_created": 0,
        "real_repository_writes": 0,
        "real_branch_created": False,
        "real_pull_request_created": False,
        "merge_performed": False,
        "live_provider_requests": 0,
        "external_dependency_resolved": False,
        "registry_activation_allowed": False,
        "production_credit": 0,
        "cer081_credit": 0,
        "next_gate": "EXPLICIT_REAL_GIT_TRANSACTION_EXECUTION_AUTHORIZATION",
    }


def authorization(plan_hash, rehearsal_hash):
    return {
        "artifact": "RATE_INTRADAY_REAL_GIT_TRANSACTION_EXECUTION_AUTHORIZATION_V1",
        "status": "REAL_GIT_TRANSACTION_EXECUTION_AUTHORIZED",
        "control_center_decision_id": DECISION,
        "current_main_sha": MAIN,
        "transaction_plan_sha256": plan_hash,
        "rehearsal_sha256": rehearsal_hash,
        "candidate_manifest_sha256": MANIFEST,
        "provider_name": PROVIDER,
        "target_branch": BRANCH,
        "single_use": True,
        "execution_consumed": False,
        "automatic_retry_allowed": False,
        "fallback_allowed": False,
        "allowed_operations": sorted(ALLOWED_OPERATIONS),
        "allowed_paths": list(EXPECTED_PATHS),
        "max_blob_count": 9,
        "max_tree_count": 1,
        "max_commit_count": 1,
        "max_ref_count": 1,
        "branch_ref_must_be_last": True,
        "direct_main_update_allowed": False,
        "pull_request_creation_allowed": False,
        "merge_allowed": False,
        "branch_delete_allowed": False,
        "credential_value_embedded": False,
        "live_provider_requests_allowed": 0,
        "production_credit_before_execution": 0,
        "cer081_credit_before_execution": 0,
    }


class RealGitExecutionAuthorizationTests(unittest.TestCase):
    def qualify(self, auth=None, plan=None, rehearsal_value=None, **overrides):
        p = plan or transaction_plan()
        plan_hash = canonical_digest(p)
        r = rehearsal_value or rehearsal(plan_hash)
        rehearsal_hash = canonical_digest(r)
        a = auth or authorization(plan_hash, rehearsal_hash)
        return validate_real_git_transaction_execution_authorization(
            a, p, r,
            expected_authorization_sha256=overrides.get("authorization_hash", canonical_digest(a)),
            expected_transaction_plan_sha256=overrides.get("plan_hash", plan_hash),
            expected_rehearsal_sha256=overrides.get("rehearsal_hash", rehearsal_hash),
            expected_current_main_sha=overrides.get("main", MAIN),
            expected_target_branch=overrides.get("branch", BRANCH),
            expected_control_center_decision_id=overrides.get("decision", DECISION),
            expected_provider_name=overrides.get("provider", PROVIDER),
        )

    def test_exact_authorization_qualifies_without_execution(self):
        result = self.qualify()
        self.assertEqual(result["validation_status"], "PASS")
        self.assertFalse(result["execution_performed"])
        self.assertFalse(result["execution_consumed"])
        self.assertFalse(result["direct_main_update_allowed"])
        self.assertFalse(result["pull_request_creation_allowed"])
        self.assertFalse(result["merge_allowed"])
        self.assertEqual(result["max_blob_count"], 9)
        self.assertEqual(result["max_tree_count"], 1)
        self.assertEqual(result["max_commit_count"], 1)
        self.assertEqual(result["max_ref_count"], 1)
        self.assertTrue(result["branch_ref_must_be_last"])
        self.assertEqual(result["repository_writes"], 0)

    def test_external_hashes_are_trust_roots(self):
        for key, kwargs, reason in (
            ("authorization", {"authorization_hash": "f" * 64}, "AUTHORIZATION_HASH_MISMATCH"),
            ("plan", {"plan_hash": "e" * 64}, "PLAN_HASH_MISMATCH"),
            ("rehearsal", {"rehearsal_hash": "d" * 64}, "REHEARSAL_HASH_MISMATCH"),
        ):
            with self.subTest(key=key), self.assertRaisesRegex(
                RealGitExecutionAuthorizationError, reason
            ):
                self.qualify(**kwargs)

    def test_plan_and_rehearsal_must_bind_exact_main_branch_and_manifest(self):
        with self.assertRaisesRegex(
            RealGitExecutionAuthorizationError, "PLAN_MAIN_MISMATCH"
        ):
            self.qualify(main="f" * 40)

        p = transaction_plan()
        p["target_branch"] = "activation/rate-v11-intraday-other"
        with self.assertRaisesRegex(
            RealGitExecutionAuthorizationError, "PLAN_BRANCH_MISMATCH"
        ):
            self.qualify(plan=p)

        p = transaction_plan()
        ph = canonical_digest(p)
        r = rehearsal(ph)
        r["candidate_manifest_sha256"] = "f" * 64
        with self.assertRaisesRegex(
            RealGitExecutionAuthorizationError, "REHEARSAL_BINDING_MISMATCH"
        ):
            self.qualify(plan=p, rehearsal_value=r)

    def test_authorization_operations_are_exact(self):
        p = transaction_plan()
        ph = canonical_digest(p)
        r = rehearsal(ph)
        rh = canonical_digest(r)
        a = authorization(ph, rh)
        a["allowed_operations"] = ["CREATE_BLOBS", "CREATE_TREE", "CREATE_COMMIT"]
        with self.assertRaisesRegex(
            RealGitExecutionAuthorizationError, "OPERATIONS_INVALID"
        ):
            self.qualify(auth=a, plan=p, rehearsal_value=r)

        a = authorization(ph, rh)
        a["allowed_operations"].append("MERGE")
        with self.assertRaisesRegex(
            RealGitExecutionAuthorizationError, "OPERATIONS_INVALID"
        ):
            self.qualify(auth=a, plan=p, rehearsal_value=r)

    def test_authorization_object_budget_and_ref_last_are_exact(self):
        p = transaction_plan()
        ph = canonical_digest(p)
        r = rehearsal(ph)
        rh = canonical_digest(r)
        for field, bad in (
            ("max_blob_count", 10),
            ("max_tree_count", 2),
            ("max_commit_count", 2),
            ("max_ref_count", 2),
            ("branch_ref_must_be_last", False),
        ):
            a = authorization(ph, rh)
            a[field] = bad
            with self.subTest(field=field), self.assertRaisesRegex(
                RealGitExecutionAuthorizationError, "OBJECT_BUDGET_INVALID"
            ):
                self.qualify(auth=a, plan=p, rehearsal_value=r)

    def test_main_pr_merge_and_branch_delete_remain_forbidden(self):
        p = transaction_plan()
        ph = canonical_digest(p)
        r = rehearsal(ph)
        rh = canonical_digest(r)
        for field in (
            "direct_main_update_allowed",
            "pull_request_creation_allowed",
            "merge_allowed",
            "branch_delete_allowed",
        ):
            a = authorization(ph, rh)
            a[field] = True
            with self.subTest(field=field), self.assertRaisesRegex(
                RealGitExecutionAuthorizationError, "FORBIDDEN_ACTION_BOUNDARY_INVALID"
            ):
                self.qualify(auth=a, plan=p, rehearsal_value=r)

    def test_single_use_cannot_already_be_consumed(self):
        p = transaction_plan()
        ph = canonical_digest(p)
        r = rehearsal(ph)
        rh = canonical_digest(r)
        a = authorization(ph, rh)
        a["execution_consumed"] = True
        with self.assertRaisesRegex(
            RealGitExecutionAuthorizationError, "SINGLE_USE_BOUNDARY_INVALID"
        ):
            self.qualify(auth=a, plan=p, rehearsal_value=r)

    def test_rehearsal_must_prove_no_real_side_effects(self):
        p = transaction_plan()
        ph = canonical_digest(p)
        r = rehearsal(ph)
        r["real_repository_writes"] = 1
        with self.assertRaisesRegex(
            RealGitExecutionAuthorizationError, "REHEARSAL_BOUNDARY_INVALID"
        ):
            self.qualify(plan=p, rehearsal_value=r)


if __name__ == "__main__":
    unittest.main()

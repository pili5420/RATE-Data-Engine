"""Tests for explicit real Git transaction execution authorization."""
from __future__ import annotations

from copy import deepcopy
import unittest

from src.intraday_activation_candidate_review import canonical_digest
from src.intraday_real_git_execution_authorization import (
    EXPECTED_BUDGET,
    RealGitExecutionAuthorizationError,
    validate_real_git_execution_authorization,
)

MAIN = "1" * 40
MANIFEST = "2" * 64
PROVIDER = "Fugle"
BRANCH = "activation/rate-v11-intraday-cc-activation-apply-2026-11-04"
DECISION = "CC-REAL-GIT-EXECUTION-2026-11-04"


def plan():
    return {
        "artifact": "RATE_INTRADAY_ACTIVATION_APPLY_TRANSACTION_PLAN_V1",
        "status": "TRANSACTION_PLAN_ONLY",
        "control_center_decision_id": "CC-ACTIVATION-APPLY-2026-11-04",
        "authorization_qualification_sha256": "3" * 64,
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
        "files": {},
        "existing_file_preimage_sha256": {},
        "new_runtime_file_absence": {},
        "apply_executed": False,
        "repository_writes": 0,
        "live_provider_requests": 0,
        "external_dependency_resolved": False,
        "registry_activation_allowed": False,
        "production_credit": 0,
        "cer081_credit": 0,
        "transaction_plan_sha256": "4" * 64,
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
        "synthetic_tree_sha": "5" * 40,
        "synthetic_commit_sha": "6" * 40,
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
        "base_main_sha": MAIN,
        "transaction_plan_sha256": plan_hash,
        "rehearsal_sha256": rehearsal_hash,
        "candidate_manifest_sha256": MANIFEST,
        "target_branch": BRANCH,
        "target_base": "main",
        "provider_name": PROVIDER,
        "single_use": True,
        "automatic_retry_allowed": False,
        "fallback_allowed": False,
        "operation_budget": dict(EXPECTED_BUDGET),
        "draft_pull_request_required": True,
        "pull_request_base": "main",
        "direct_main_update_allowed": False,
        "merge_allowed": False,
        "live_provider_requests_allowed": 0,
        "credential_value_embedded": False,
        "production_credit_before_execution": 0,
        "cer081_credit_before_execution": 0,
    }


class RealGitExecutionAuthorizationTests(unittest.TestCase):
    def qualify(self, auth=None, p=None, reh=None, **overrides):
        p = p or plan()
        p_hash = canonical_digest(p)
        reh = reh or rehearsal(p_hash)
        reh_hash = canonical_digest(reh)
        auth = auth or authorization(p_hash, reh_hash)
        return validate_real_git_execution_authorization(
            auth,
            p,
            reh,
            expected_authorization_sha256=overrides.get("auth_hash", canonical_digest(auth)),
            expected_transaction_plan_sha256=overrides.get("plan_hash", p_hash),
            expected_rehearsal_sha256=overrides.get("rehearsal_hash", reh_hash),
            expected_base_main_sha=overrides.get("main", MAIN),
            expected_candidate_manifest_sha256=overrides.get("manifest", MANIFEST),
            expected_target_branch=overrides.get("branch", BRANCH),
            expected_provider_name=overrides.get("provider", PROVIDER),
            expected_decision_id=overrides.get("decision", DECISION),
        )

    def test_exact_authorization_qualifies_without_execution(self):
        result = self.qualify()
        self.assertEqual(result["validation_status"], "PASS")
        self.assertTrue(result["authorization_valid"])
        self.assertFalse(result["execution_performed"])
        self.assertEqual(result["real_git_operations"], 0)
        self.assertFalse(result["direct_main_update_allowed"])
        self.assertFalse(result["merge_allowed"])
        self.assertTrue(result["draft_pull_request_required"])

    def test_plan_rehearsal_and_authorization_are_independently_hash_bound(self):
        with self.assertRaisesRegex(
            RealGitExecutionAuthorizationError, "PLAN_HASH_MISMATCH"
        ):
            self.qualify(plan_hash="f" * 64)
        with self.assertRaisesRegex(
            RealGitExecutionAuthorizationError, "REHEARSAL_HASH_MISMATCH"
        ):
            self.qualify(rehearsal_hash="e" * 64)
        with self.assertRaisesRegex(
            RealGitExecutionAuthorizationError, "AUTHORIZATION_HASH_MISMATCH"
        ):
            self.qualify(auth_hash="d" * 64)

    def test_operation_budget_is_exact(self):
        p = plan()
        ph = canonical_digest(p)
        reh = rehearsal(ph)
        rh = canonical_digest(reh)
        for key, value in (
            ("create_blob_count", 8),
            ("create_tree_count", 2),
            ("create_commit_count", 2),
            ("create_branch_ref_count", 0),
            ("create_draft_pull_request_count", 0),
            ("update_main_ref_count", 1),
            ("merge_count", 1),
        ):
            auth = authorization(ph, rh)
            auth["operation_budget"][key] = value
            with self.subTest(key=key), self.assertRaisesRegex(
                RealGitExecutionAuthorizationError, "OPERATION_BUDGET_INVALID"
            ):
                self.qualify(auth=auth, p=p, reh=reh)

    def test_single_use_retry_fallback_and_pr_boundary_are_exact(self):
        p = plan()
        ph = canonical_digest(p)
        reh = rehearsal(ph)
        rh = canonical_digest(reh)
        for field, value, reason in (
            ("single_use", False, "SINGLE_USE_BOUNDARY_INVALID"),
            ("automatic_retry_allowed", True, "SINGLE_USE_BOUNDARY_INVALID"),
            ("fallback_allowed", True, "SINGLE_USE_BOUNDARY_INVALID"),
            ("draft_pull_request_required", False, "PR_BOUNDARY_INVALID"),
            ("direct_main_update_allowed", True, "PR_BOUNDARY_INVALID"),
            ("merge_allowed", True, "PR_BOUNDARY_INVALID"),
        ):
            auth = authorization(ph, rh)
            auth[field] = value
            with self.subTest(field=field), self.assertRaisesRegex(
                RealGitExecutionAuthorizationError, reason
            ):
                self.qualify(auth=auth, p=p, reh=reh)

    def test_main_manifest_branch_provider_and_decision_are_bound(self):
        with self.assertRaisesRegex(
            RealGitExecutionAuthorizationError, "PLAN_MAIN_MISMATCH"
        ):
            self.qualify(main="f" * 40)
        with self.assertRaisesRegex(
            RealGitExecutionAuthorizationError, "PLAN_MANIFEST_MISMATCH"
        ):
            self.qualify(manifest="e" * 64)
        with self.assertRaisesRegex(
            RealGitExecutionAuthorizationError, "PLAN_BRANCH_MISMATCH"
        ):
            self.qualify(branch="activation/rate-v11-intraday-other")
        with self.assertRaisesRegex(
            RealGitExecutionAuthorizationError, "PLAN_PROVIDER_MISMATCH"
        ):
            self.qualify(provider="OTHER")
        with self.assertRaisesRegex(
            RealGitExecutionAuthorizationError, "DECISION_ID_MISMATCH"
        ):
            self.qualify(decision="OTHER")

    def test_rehearsal_must_prove_no_real_effects_and_main_unchanged(self):
        p = plan()
        ph = canonical_digest(p)
        reh = rehearsal(ph)
        reh["main_ref_unchanged"] = False
        with self.assertRaisesRegex(
            RealGitExecutionAuthorizationError, "REHEARSAL_BOUNDARY_INVALID"
        ):
            self.qualify(p=p, reh=reh)

        reh = rehearsal(ph)
        reh["real_branch_created"] = True
        with self.assertRaisesRegex(
            RealGitExecutionAuthorizationError, "REHEARSAL_BOUNDARY_INVALID"
        ):
            self.qualify(p=p, reh=reh)

    def test_authorization_cannot_include_live_requests_or_precredit(self):
        p = plan()
        ph = canonical_digest(p)
        reh = rehearsal(ph)
        rh = canonical_digest(reh)
        auth = authorization(ph, rh)
        auth["live_provider_requests_allowed"] = 1
        with self.assertRaisesRegex(
            RealGitExecutionAuthorizationError, "PRODUCTION_BOUNDARY_INVALID"
        ):
            self.qualify(auth=auth, p=p, reh=reh)
        auth = authorization(ph, rh)
        auth["production_credit_before_execution"] = 1
        with self.assertRaisesRegex(
            RealGitExecutionAuthorizationError, "PRODUCTION_BOUNDARY_INVALID"
        ):
            self.qualify(auth=auth, p=p, reh=reh)


if __name__ == "__main__":
    unittest.main()

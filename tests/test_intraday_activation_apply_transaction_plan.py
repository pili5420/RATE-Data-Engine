"""Tests for deterministic non-mutating activation apply transaction plans."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import unittest

from src.intraday_activation_apply_authorization import EXPECTED_PATHS
from src.intraday_activation_apply_transaction_plan import (
    ActivationApplyTransactionPlanError,
    build_activation_apply_transaction_plan,
)
from src.intraday_activation_candidate_materialization import candidate_manifest_sha256
from src.intraday_activation_candidate_review import canonical_digest
from src.intraday_activation_delta_plan import NEW_RUNTIME_FILES
from src.intraday_activation_readiness import (
    ALLOWED_EXISTING_MUTATION_PATHS,
    repo_preimage_hashes,
)

MAIN = "1" * 40
PROVIDER = "Fugle"
DECISION = "CC-ACTIVATION-APPLY-2026-11-04"


def candidate_files():
    result = {}
    for index, path in enumerate(EXPECTED_PATHS):
        result[path] = f"candidate-{index}-{path}\n"
    return result


def qualification(manifest):
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


class ActivationApplyTransactionPlanTests(unittest.TestCase):
    def build(self, files=None, qual=None, **overrides):
        c = files or candidate_files()
        manifest = candidate_manifest_sha256(c)
        q = qual or qualification(manifest)
        return build_activation_apply_transaction_plan(
            q,
            c,
            expected_authorization_qualification_sha256=overrides.get(
                "qualification_hash", canonical_digest(q)
            ),
            expected_current_main_sha=overrides.get("main", MAIN),
            expected_candidate_manifest_sha256=overrides.get("manifest", manifest),
            expected_control_center_decision_id=overrides.get("decision", DECISION),
            expected_provider_name=overrides.get("provider", PROVIDER),
        )

    def test_exact_transaction_plan_is_deterministic_and_non_mutating(self):
        before = repo_preimage_hashes()
        one = self.build()
        two = self.build()
        self.assertEqual(one, two)
        self.assertEqual(one["status"], "TRANSACTION_PLAN_ONLY")
        self.assertFalse(one["merge_allowed_by_plan"])
        self.assertFalse(one["direct_main_update_allowed"])
        self.assertFalse(one["apply_executed"])
        self.assertEqual(one["repository_writes"], 0)
        self.assertEqual(len(one["files"]), 9)
        self.assertEqual(repo_preimage_hashes(), before)

    def test_existing_and_new_operations_are_exact(self):
        plan = self.build()
        for path in ALLOWED_EXISTING_MUTATION_PATHS:
            self.assertEqual(plan["files"][path]["operation"], "REPLACE_EXISTING")
            self.assertEqual(
                plan["files"][path]["base_sha256"],
                repo_preimage_hashes()[path],
            )
        for path in NEW_RUNTIME_FILES:
            self.assertEqual(plan["files"][path]["operation"], "CREATE_NEW")
            self.assertIsNone(plan["files"][path]["base_sha256"])
            self.assertTrue(plan["new_runtime_file_absence"][path])

    def test_content_sha256_and_git_blob_sha1_are_bound(self):
        files = candidate_files()
        plan = self.build(files=files)
        path = EXPECTED_PATHS[0]
        content = files[path].encode()
        expected_blob = hashlib.sha1(
            f"blob {len(content)}\0".encode() + content
        ).hexdigest()
        self.assertEqual(
            plan["files"][path]["content_sha256"],
            hashlib.sha256(content).hexdigest(),
        )
        self.assertEqual(plan["files"][path]["git_blob_sha1"], expected_blob)

    def test_authorization_qualification_hash_and_boundary_are_required(self):
        with self.assertRaisesRegex(
            ActivationApplyTransactionPlanError,
            "AUTHORIZATION_QUALIFICATION_HASH_MISMATCH",
        ):
            self.build(qualification_hash="f" * 64)

        files = candidate_files()
        manifest = candidate_manifest_sha256(files)
        q = qualification(manifest)
        q["single_use"] = False
        with self.assertRaisesRegex(
            ActivationApplyTransactionPlanError, "AUTHORIZATION_BOUNDARY_INVALID"
        ):
            self.build(files=files, qual=q)

    def test_candidate_manifest_and_file_set_are_exact(self):
        with self.assertRaisesRegex(
            ActivationApplyTransactionPlanError, "CANDIDATE_MANIFEST_BINDING_MISMATCH"
        ):
            self.build(manifest="f" * 64)

        files = candidate_files()
        manifest = candidate_manifest_sha256(files)
        q = qualification(manifest)
        tampered = dict(files)
        tampered[EXPECTED_PATHS[0]] += "tamper\n"
        with self.assertRaisesRegex(
            ActivationApplyTransactionPlanError, "CANDIDATE_MANIFEST_HASH_MISMATCH"
        ):
            build_activation_apply_transaction_plan(
                q,
                tampered,
                expected_authorization_qualification_sha256=canonical_digest(q),
                expected_current_main_sha=MAIN,
                expected_candidate_manifest_sha256=manifest,
                expected_control_center_decision_id=DECISION,
                expected_provider_name=PROVIDER,
            )

        valid_files = candidate_files()
        valid_manifest = candidate_manifest_sha256(valid_files)
        q = qualification(valid_manifest)
        invalid_files = dict(valid_files)
        invalid_files["config/UNAUTHORIZED.json"] = "x"
        with self.assertRaisesRegex(
            ActivationApplyTransactionPlanError, "CANDIDATE_FILE_SET_INVALID"
        ):
            build_activation_apply_transaction_plan(
                q,
                invalid_files,
                expected_authorization_qualification_sha256=canonical_digest(q),
                expected_current_main_sha=MAIN,
                expected_candidate_manifest_sha256=valid_manifest,
                expected_control_center_decision_id=DECISION,
                expected_provider_name=PROVIDER,
            )

    def test_main_provider_and_decision_are_exact(self):
        with self.assertRaisesRegex(
            ActivationApplyTransactionPlanError, "CURRENT_MAIN_MISMATCH"
        ):
            self.build(main="f" * 40)
        with self.assertRaisesRegex(
            ActivationApplyTransactionPlanError, "PROVIDER_MISMATCH"
        ):
            self.build(provider="OTHER")
        with self.assertRaisesRegex(
            ActivationApplyTransactionPlanError, "DECISION_ID_MISMATCH"
        ):
            self.build(decision="OTHER")

    def test_decision_id_must_produce_a_valid_git_branch_name(self):
        for invalid in (
            "BAD..RANGE",
            "TRAILING.",
            "reserved.lock",
        ):
            with self.subTest(invalid=invalid), self.assertRaisesRegex(
                ActivationApplyTransactionPlanError, "EXPECTED_DECISION_ID_INVALID"
            ):
                self.build(decision=invalid)

    def test_target_branch_is_deterministic_and_never_main(self):
        plan = self.build()
        self.assertEqual(
            plan["target_branch"],
            "activation/rate-v11-intraday-" + DECISION.lower(),
        )
        self.assertNotEqual(plan["target_branch"], "main")
        self.assertNotIn("..", plan["target_branch"])
        self.assertFalse(plan["target_branch"].endswith("."))
        self.assertFalse(plan["target_branch"].lower().endswith(".lock"))

    def test_plan_hash_changes_when_candidate_content_changes(self):
        one = self.build()
        files = candidate_files()
        files[EXPECTED_PATHS[0]] += "changed\n"
        manifest = candidate_manifest_sha256(files)
        q = qualification(manifest)
        two = self.build(files=files, qual=q)
        self.assertNotEqual(
            one["transaction_plan_sha256"],
            two["transaction_plan_sha256"],
        )


if __name__ == "__main__":
    unittest.main()

"""Tests for final-main rebase/apply readiness without applying activation."""
from __future__ import annotations

from copy import deepcopy
import unittest

from src.intraday_activation_candidate_review import canonical_digest
from src.intraday_activation_delta_plan import NEW_RUNTIME_FILES
from src.intraday_activation_readiness import (
    ALLOWED_EXISTING_MUTATION_PATHS,
    repo_preimage_hashes,
)
from src.intraday_final_main_apply_readiness import (
    FinalMainApplyReadinessError,
    review_final_main_activation_apply_readiness,
)

MAIN = "1" * 40
PROVIDER = "Fugle"
LICENSE = "OWNER_ASSUMED_AUTHORIZED"
ENDPOINT = "https://api.fugle.tw/marketdata/v1.0/stock/intraday/quote/{symbol}"
SECRET = "FUGLE_API_KEY"
MANIFEST = "2" * 64


def live_binding():
    return {
        "artifact": "RATE_INTRADAY_LIVE_EVIDENCE_BINDING_V1",
        "validation_status": "PASS",
        "binding_status": "LIVE_EVIDENCE_BOUND",
        "provider_name": PROVIDER,
        "license_basis": LICENSE,
        "candidate_base_main_sha": "3" * 40,
        "candidate_manifest_sha256": "4" * 64,
        "synthetic_review_sha256": "5" * 64,
        "live_review_sha256": "6" * 64,
        "provider_acceptance_sha256": "7" * 64,
        "provider_acceptance_decision_sha256": "8" * 64,
        "live_evidence_cadences": ["09:30"],
        "authorized_provider_cadences": ["09:30", "12:00"],
        "live_untested_cadences": ["12:00"],
        "coverage": "30/30",
        "market_counts": {"TWSE": 25, "TPEX": 5},
        "final_main_rebase_required": True,
        "provider_accepted": True,
        "apply_allowed": False,
        "activation_execution_allowed": False,
        "external_dependency_resolved": False,
        "registry_activation_allowed": False,
        "production_credit": 0,
        "cer081_credit": 0,
        "next_gate": "FINAL_MAIN_REBASE_AND_ACTIVATION_APPLY_REVIEW",
    }


def delta_plan():
    return {
        "artifact": "RATE_INTRADAY_ACTIVATION_DELTA_PLAN_V1",
        "validation_status": "PASS",
        "plan_status": "READY_FOR_SEPARATE_ACTIVATION_IMPLEMENTATION_REVIEW",
        "main_sha": MAIN,
        "control_center_activation_decision_id": "CC-FINAL-APPLY",
        "provider_name": PROVIDER,
        "license_basis": LICENSE,
        "provider_endpoint_template": ENDPOINT,
        "credential_boundary": {
            "store": "GITHUB_ACTIONS_SECRET",
            "secret_name": SECRET,
            "secret_value_embedded": False,
        },
        "existing_file_preimage_sha256": repo_preimage_hashes(),
        "existing_mutation_paths": list(ALLOWED_EXISTING_MUTATION_PATHS),
        "new_runtime_files": list(NEW_RUNTIME_FILES),
        "mutation_specs": {},
        "required_markets": ["TWSE", "TPEX"],
        "authorized_cadences": ["09:30", "12:00"],
        "fallback_allowed": False,
        "automatic_retry_allowed": False,
        "apply_allowed": False,
        "activation_execution_allowed": False,
        "external_dependency_resolved": False,
        "registry_activation_allowed": False,
        "network_requests": 0,
        "credential_access": 0,
        "registry_mutations": 0,
        "scheduler_mutations": 0,
        "production_state_mutations": 0,
        "production_credit": 0,
        "cer081_credit": 0,
    }


def synthetic_review():
    return {
        "artifact": "RATE_INTRADAY_FULL_SYNTHETIC_ACTIVATION_CANDIDATE_REVIEW_V1",
        "validation_status": "PASS",
        "review_disposition": "READY_FOR_LIVE_EVIDENCE_BOUND_ACTIVATION_REVIEW",
        "main_sha": MAIN,
        "delta_plan_sha256": canonical_digest(delta_plan()),
        "candidate_manifest_sha256": MANIFEST,
        "runtime_sha256": "9" * 64,
        "acquisition_sha256": "a" * 64,
        "provider_name": PROVIDER,
        "trading_date": "2026-11-04",
        "cadence": "09:30",
        "subreview_sha256": {
            "scaffold": "b" * 64,
            "syntax": "c" * 64,
            "runtime": "d" * 64,
            "acquisition": "e" * 64,
            "materialization": "f" * 64,
            "materialized_review": "0" * 64,
        },
        "coverage": "30/30",
        "market_counts": {"TWSE": 25, "TPEX": 5},
        "real_network_requests": 0,
        "real_credential_access": 0,
        "repository_writes": 0,
        "provider_accepted": False,
        "apply_allowed": False,
        "activation_execution_allowed": False,
        "external_dependency_resolved": False,
        "registry_activation_allowed": False,
        "production_credit": 0,
        "cer081_credit": 0,
        "next_gate": "LIVE_PROVIDER_EVIDENCE_BINDING",
    }


class FinalMainApplyReadinessTests(unittest.TestCase):
    def review(self, live=None, delta=None, synthetic=None, **overrides):
        liv = live or live_binding()
        dep = delta or delta_plan()
        syn = synthetic or synthetic_review()
        return review_final_main_activation_apply_readiness(
            liv,
            dep,
            syn,
            expected_live_binding_sha256=overrides.get(
                "live_hash", canonical_digest(liv)
            ),
            expected_rebased_delta_plan_sha256=overrides.get(
                "delta_hash", canonical_digest(dep)
            ),
            expected_rebased_synthetic_review_sha256=overrides.get(
                "synthetic_hash", canonical_digest(syn)
            ),
            expected_current_main_sha=overrides.get("main", MAIN),
            expected_rebased_candidate_manifest_sha256=overrides.get(
                "manifest", MANIFEST
            ),
            expected_provider_name=overrides.get("provider", PROVIDER),
            expected_license_basis=overrides.get("license", LICENSE),
            expected_endpoint_template=overrides.get("endpoint", ENDPOINT),
            expected_secret_name=overrides.get("secret", SECRET),
        )

    def test_exact_final_main_review_passes_without_apply(self):
        result = self.review()
        self.assertEqual(result["validation_status"], "PASS")
        self.assertEqual(
            result["review_disposition"],
            "READY_FOR_CONTROL_CENTER_ACTIVATION_APPLY_AUTHORIZATION",
        )
        self.assertEqual(result["current_main_sha"], MAIN)
        self.assertEqual(result["live_evidence_cadences"], ["09:30"])
        self.assertEqual(result["live_untested_cadences"], ["12:00"])
        self.assertFalse(result["historical_evidence_rewritten"])
        self.assertTrue(result["provider_accepted"])
        self.assertFalse(result["apply_allowed"])
        self.assertFalse(result["activation_execution_allowed"])
        self.assertEqual(
            result["next_gate"],
            "EXPLICIT_CONTROL_CENTER_ACTIVATION_APPLY_AUTHORIZATION",
        )

    def test_historical_live_binding_is_hash_bound_and_not_rewritten(self):
        with self.assertRaisesRegex(
            FinalMainApplyReadinessError, "LIVE_BINDING_HASH_MISMATCH"
        ):
            self.review(live_hash="f" * 64)
        live = live_binding()
        live["candidate_base_main_sha"] = MAIN
        with self.assertRaisesRegex(
            FinalMainApplyReadinessError, "LIVE_BINDING_HASH_MISMATCH"
        ):
            self.review(live=live, live_hash=canonical_digest(live_binding()))

    def test_current_repo_preimages_are_not_caller_replaceable(self):
        delta = delta_plan()
        first = next(iter(delta["existing_file_preimage_sha256"]))
        delta["existing_file_preimage_sha256"][first] = "f" * 64
        with self.assertRaisesRegex(
            FinalMainApplyReadinessError, "PREIMAGE_MISMATCH"
        ):
            self.review(delta=delta)

    def test_rebased_delta_is_bound_to_current_main_provider_endpoint_secret(self):
        for field, value, reason in (
            ("main_sha", "f" * 40, "DELTA_MAIN_MISMATCH"),
            ("provider_name", "OTHER", "DELTA_PROVIDER_MISMATCH"),
            ("provider_endpoint_template", "https://other.invalid/{symbol}", "DELTA_ENDPOINT_MISMATCH"),
            ("license_basis", "PROVIDER_WRITTEN_CONFIRMED", "DELTA_LICENSE_MISMATCH"),
        ):
            delta = delta_plan()
            delta[field] = value
            with self.subTest(field=field), self.assertRaisesRegex(
                FinalMainApplyReadinessError, reason
            ):
                self.review(delta=delta)
        delta = delta_plan()
        delta["credential_boundary"]["secret_name"] = "OTHER_SECRET"
        with self.assertRaisesRegex(
            FinalMainApplyReadinessError, "DELTA_CREDENTIAL_MISMATCH"
        ):
            self.review(delta=delta)

    def test_rebased_synthetic_review_is_bound_to_current_main_and_manifest(self):
        synthetic = synthetic_review()
        synthetic["main_sha"] = "f" * 40
        with self.assertRaisesRegex(
            FinalMainApplyReadinessError, "SYNTHETIC_MAIN_MISMATCH"
        ):
            self.review(synthetic=synthetic)
        synthetic = synthetic_review()
        synthetic["candidate_manifest_sha256"] = "f" * 64
        with self.assertRaisesRegex(
            FinalMainApplyReadinessError, "CANDIDATE_MANIFEST_MISMATCH"
        ):
            self.review(synthetic=synthetic)

    def test_live_cadence_credit_remains_single_scope(self):
        live = live_binding()
        live["live_evidence_cadences"] = ["09:30", "12:00"]
        live["live_untested_cadences"] = []
        with self.assertRaisesRegex(
            FinalMainApplyReadinessError, "LIVE_CADENCE_SCOPE_INVALID"
        ):
            self.review(live=live)

    def test_no_input_can_claim_apply_or_credit(self):
        delta = delta_plan()
        delta["apply_allowed"] = True
        with self.assertRaisesRegex(
            FinalMainApplyReadinessError, "DELTA_PREMATURE_STATE"
        ):
            self.review(delta=delta)
        synthetic = synthetic_review()
        synthetic["production_credit"] = 1
        with self.assertRaisesRegex(
            FinalMainApplyReadinessError, "SYNTHETIC_BOUNDARY_INVALID"
        ):
            self.review(synthetic=synthetic)
        live = live_binding()
        live["activation_execution_allowed"] = True
        with self.assertRaisesRegex(
            FinalMainApplyReadinessError, "LIVE_BINDING_PREMATURE_STATE"
        ):
            self.review(live=live)


if __name__ == "__main__":
    unittest.main()

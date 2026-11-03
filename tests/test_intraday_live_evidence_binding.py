"""Tests for binding live provider evidence to one reviewed activation candidate."""
from __future__ import annotations

from copy import deepcopy
import unittest

from src.intraday_activation_candidate_review import canonical_digest
from src.intraday_live_evidence_binding import (
    LiveEvidenceBindingError,
    bind_live_evidence_to_activation_candidate,
)

PROVIDER = "Fugle"
LICENSE = "OWNER_ASSUMED_AUTHORIZED"
CANDIDATE_MAIN = "1" * 40
CANDIDATE_MANIFEST = "2" * 64
ACCEPTANCE_DECISION = "3" * 64


def synthetic_review(cadence="09:30"):
    return {
        "artifact": "RATE_INTRADAY_FULL_SYNTHETIC_ACTIVATION_CANDIDATE_REVIEW_V1",
        "validation_status": "PASS",
        "review_disposition": "READY_FOR_LIVE_EVIDENCE_BOUND_ACTIVATION_REVIEW",
        "main_sha": CANDIDATE_MAIN,
        "delta_plan_sha256": "a" * 64,
        "candidate_manifest_sha256": CANDIDATE_MANIFEST,
        "runtime_sha256": "b" * 64,
        "acquisition_sha256": "c" * 64,
        "provider_name": PROVIDER,
        "trading_date": "2026-11-04",
        "cadence": cadence,
        "subreview_sha256": {
            "scaffold": "d" * 64,
            "syntax": "e" * 64,
            "runtime": "f" * 64,
            "acquisition": "0" * 64,
            "materialization": "1" * 64,
            "materialized_review": "2" * 64,
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


def live_review(cadence="09:30"):
    return {
        "artifact": "RATE_INTRADAY_SINGLE_LIVE_QUALIFICATION_REVIEW_V1",
        "validation_status": "PASS",
        "review_disposition": "READY_FOR_CONTROL_CENTER_PROVIDER_ACCEPTANCE",
        "engineering_source_sha": "4" * 40,
        "trigger_commit_sha": "5" * 40,
        "workflow_run_id": 12345,
        "workflow_job_id": 67890,
        "provider_name": PROVIDER,
        "trading_date": "2026-11-04",
        "cadence": cadence,
        "result_sha256": "6" * 64,
        "market_coverage": "30/30",
        "market_counts": {"TWSE": 25, "TPEX": 5},
        "network_requests": 30,
        "http_redirects_followed": 0,
        "automatic_retries": 0,
        "fallback_used": False,
        "secret_exposure": False,
        "provider_accepted": False,
        "activation_execution_allowed": False,
        "external_dependency_resolved": False,
        "production_credit": 0,
        "cer081_credit": 0,
    }


def provider_acceptance():
    return {
        "artifact": "RATE_INTRADAY_PROVIDER_ACCEPTANCE_V1",
        "validation_status": "PASS",
        "control_center_decision_id": "CC-PROVIDER-ACCEPTANCE",
        "decision_sha256": ACCEPTANCE_DECISION,
        "main_sha": "7" * 40,
        "provider_name": PROVIDER,
        "license_basis": LICENSE,
        "provider_accepted": True,
        "required_markets": ["TPEX", "TWSE"],
        "authorized_cadences": ["09:30", "12:00"],
        "external_dependency_id": "EXTERNAL_AUTHORIZED_INTRADAY_FEED_DEPENDENCY",
        "source_registry_dataset_id": "authorized_market_intraday",
        "fallback_allowed": False,
        "automatic_retry_allowed": False,
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
        "next_gate": "SEPARATE_CONTROL_CENTER_ACTIVATION_IMPLEMENTATION",
    }


class LiveEvidenceBindingTests(unittest.TestCase):
    def bind(self, *, cadence="09:30", synthetic=None, live=None, acceptance=None, **overrides):
        syn = synthetic or synthetic_review(cadence)
        liv = live or live_review(cadence)
        acc = acceptance or provider_acceptance()
        return bind_live_evidence_to_activation_candidate(
            syn,
            liv,
            acc,
            expected_synthetic_review_sha256=overrides.get(
                "synthetic_hash", canonical_digest(syn)
            ),
            expected_live_review_sha256=overrides.get(
                "live_hash", canonical_digest(liv)
            ),
            expected_provider_acceptance_sha256=overrides.get(
                "acceptance_hash", canonical_digest(acc)
            ),
            expected_provider_acceptance_decision_sha256=overrides.get(
                "decision_hash", ACCEPTANCE_DECISION
            ),
            expected_candidate_manifest_sha256=overrides.get(
                "manifest", CANDIDATE_MANIFEST
            ),
            expected_candidate_base_main_sha=overrides.get(
                "candidate_main", CANDIDATE_MAIN
            ),
            expected_provider_name=overrides.get("provider", PROVIDER),
            expected_live_cadence=overrides.get("live_cadence", cadence),
            expected_license_basis=overrides.get("license", LICENSE),
        )

    def test_0930_live_evidence_is_bound_without_inflating_1200_credit(self):
        result = self.bind()
        self.assertEqual(result["validation_status"], "PASS")
        self.assertEqual(result["binding_status"], "LIVE_EVIDENCE_BOUND")
        self.assertEqual(result["live_evidence_cadences"], ["09:30"])
        self.assertEqual(result["live_untested_cadences"], ["12:00"])
        self.assertEqual(result["authorized_provider_cadences"], ["09:30", "12:00"])
        self.assertTrue(result["final_main_rebase_required"])
        self.assertTrue(result["provider_accepted"])
        self.assertFalse(result["activation_execution_allowed"])
        self.assertFalse(result["external_dependency_resolved"])
        self.assertEqual(result["next_gate"], "FINAL_MAIN_REBASE_AND_ACTIVATION_APPLY_REVIEW")

    def test_1200_live_evidence_scope_is_symmetric(self):
        result = self.bind(cadence="12:00")
        self.assertEqual(result["live_evidence_cadences"], ["12:00"])
        self.assertEqual(result["live_untested_cadences"], ["09:30"])

    def test_all_three_evidence_objects_are_externally_hash_bound(self):
        with self.assertRaisesRegex(
            LiveEvidenceBindingError, "SYNTHETIC_REVIEW_HASH_MISMATCH"
        ):
            self.bind(synthetic_hash="f" * 64)
        with self.assertRaisesRegex(
            LiveEvidenceBindingError, "LIVE_REVIEW_HASH_MISMATCH"
        ):
            self.bind(live_hash="e" * 64)
        with self.assertRaisesRegex(
            LiveEvidenceBindingError, "PROVIDER_ACCEPTANCE_HASH_MISMATCH"
        ):
            self.bind(acceptance_hash="d" * 64)

    def test_provider_acceptance_decision_hash_is_separately_bound(self):
        with self.assertRaisesRegex(
            LiveEvidenceBindingError, "PROVIDER_DECISION_HASH_MISMATCH"
        ):
            self.bind(decision_hash="c" * 64)

    def test_candidate_manifest_and_base_main_are_externally_bound(self):
        with self.assertRaisesRegex(
            LiveEvidenceBindingError, "CANDIDATE_MANIFEST_HASH_MISMATCH"
        ):
            self.bind(manifest="b" * 64)
        with self.assertRaisesRegex(
            LiveEvidenceBindingError, "CANDIDATE_MAIN_MISMATCH"
        ):
            self.bind(candidate_main="8" * 40)

    def test_provider_and_live_cadence_must_match_all_evidence(self):
        live = live_review()
        live["provider_name"] = "OTHER"
        with self.assertRaisesRegex(
            LiveEvidenceBindingError, "LIVE_PROVIDER_MISMATCH"
        ):
            self.bind(live=live)
        live = live_review("12:00")
        with self.assertRaisesRegex(
            LiveEvidenceBindingError, "LIVE_CADENCE_MISMATCH"
        ):
            self.bind(live=live)

    def test_live_runtime_contract_cannot_be_relaxed(self):
        for field, value in (
            ("network_requests", 29),
            ("http_redirects_followed", 1),
            ("automatic_retries", 1),
            ("fallback_used", True),
            ("secret_exposure", True),
        ):
            live = live_review()
            live[field] = value
            with self.subTest(field=field), self.assertRaisesRegex(
                LiveEvidenceBindingError, "LIVE_RUNTIME_BOUNDARY_INVALID"
            ):
                self.bind(live=live)

    def test_provider_acceptance_cannot_claim_activation_or_credit(self):
        for field, value in (
            ("activation_execution_allowed", True),
            ("external_dependency_resolved", True),
            ("registry_activation_allowed", True),
            ("production_credit", 1),
            ("cer081_credit", 1),
        ):
            acceptance = provider_acceptance()
            acceptance[field] = value
            with self.subTest(field=field), self.assertRaisesRegex(
                LiveEvidenceBindingError, "PROVIDER_ACCEPTANCE_BOUNDARY_INVALID"
            ):
                self.bind(acceptance=acceptance)

    def test_owner_assumed_license_basis_remains_explicit(self):
        result = self.bind()
        self.assertEqual(result["license_basis"], "OWNER_ASSUMED_AUTHORIZED")
        with self.assertRaisesRegex(
            LiveEvidenceBindingError, "LICENSE_BASIS_MISMATCH"
        ):
            self.bind(license="PROVIDER_WRITTEN_CONFIRMED")


if __name__ == "__main__":
    unittest.main()

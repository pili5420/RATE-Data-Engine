"""Tests for the in-memory intraday activation candidate scaffold builder."""
from __future__ import annotations

from copy import deepcopy
import unittest

from src.intraday_activation_candidate_review import canonical_digest
from src.intraday_activation_candidate_scaffold import (
    ActivationCandidateScaffoldError,
    build_activation_candidate_scaffold,
)
from src.intraday_activation_delta_plan import NEW_RUNTIME_FILES
from src.intraday_activation_readiness import (
    ALLOWED_EXISTING_MUTATION_PATHS,
    repo_preimage_hashes,
)

MAIN = "1" * 40
PROVIDER = "Fugle"
ENDPOINT = "https://api.fugle.tw/marketdata/v1.0/stock/intraday/quote/{symbol}"
SECRET = "FUGLE_API_KEY"


def plan():
    return {
        "artifact": "RATE_INTRADAY_ACTIVATION_DELTA_PLAN_V1",
        "validation_status": "PASS",
        "plan_status": "READY_FOR_SEPARATE_ACTIVATION_IMPLEMENTATION_REVIEW",
        "main_sha": MAIN,
        "control_center_activation_decision_id": "CC-ACTIVATION",
        "provider_name": PROVIDER,
        "license_basis": "OWNER_ASSUMED_AUTHORIZED",
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


class ActivationCandidateScaffoldTests(unittest.TestCase):
    def build(self, delta=None, **kwargs):
        current = delta or plan()
        return build_activation_candidate_scaffold(
            current,
            expected_delta_plan_sha256=kwargs.get("plan_hash", canonical_digest(current)),
            expected_main_sha=kwargs.get("main", MAIN),
            expected_provider_name=kwargs.get("provider", PROVIDER),
            expected_endpoint_template=kwargs.get("endpoint", ENDPOINT),
            expected_secret_name=kwargs.get("secret", SECRET),
        )

    def test_exact_scaffold_passes_static_review_without_writes(self):
        result = self.build()
        self.assertEqual(result["validation_status"], "PASS")
        self.assertEqual(result["scaffold_status"], "DESIGN_SCAFFOLD_ONLY")
        self.assertEqual(result["static_review"]["validation_status"], "PASS")
        self.assertFalse(result["apply_allowed"])
        self.assertEqual(result["repository_writes"], 0)
        self.assertEqual(len(result["candidate_files"]), 9)

    def test_scaffold_does_not_mutate_delta_or_repo_preimages(self):
        delta = plan()
        before = deepcopy(delta)
        preimages = repo_preimage_hashes()
        result = self.build(delta)
        self.assertEqual(delta, before)
        self.assertEqual(repo_preimage_hashes(), preimages)
        result["candidate_files"]["config/SOURCE_REGISTRY.json"] = "{}"
        self.assertEqual(delta, before)

    def test_phase2_scaffold_closes_all_three_hard_blockers(self):
        phase2 = self.build()["candidate_files"]["src/phase2_production.py"]
        self.assertNotIn(
            'raise RuntimeError("PUBLIC_OFFICIAL_PARTIAL_RUNTIME_REQUIRED")',
            phase2,
        )
        self.assertNotIn(
            'require(cadence in {"07:30", "19:30"}, "PUBLIC_OFFICIAL_PARTIAL_RUNTIME_REQUIRED")',
            phase2,
        )
        self.assertNotIn('market_intraday_price_gate="BLOCKED_EXTERNAL"', phase2)
        self.assertNotIn(
            'decision.get("full_intraday_decision_status") == "BLOCKED_EXTERNAL"',
            phase2,
        )
        self.assertIn("def intraday_decision_gate_status(cadence):", phase2)
        self.assertIn(
            'return "PASS" if cadence in {"09:30", "12:00"} else "NOT_APPLICABLE"',
            phase2,
        )
        self.assertIn("require(cadence in CADENCES", phase2)

    def test_registry_scaffold_is_provider_bound(self):
        files = self.build()["candidate_files"]
        self.assertIn('"provider": "Fugle"', files["config/SOURCE_REGISTRY.json"])
        self.assertIn('"authorization_status": "PASS"', files["config/SOURCE_REGISTRY.json"])
        self.assertNotIn(
            '"blocked_dependency"',
            files["config/RATE_PRODUCTION_OFFICIAL_SOURCE_REGISTRY_V1.json"],
        )

    def test_scheduler_scaffold_switches_from_public_partial_to_phase2(self):
        files = self.build()["candidate_files"]
        for path in (
            ".github/workflows/rate_production_0930_scheduler.yml",
            ".github/workflows/rate_production_1200_scheduler.yml",
        ):
            text = files[path]
            self.assertNotIn("--public-official-partial", text)
            self.assertIn("scripts/acquire_intraday_provider_feed.py", text)
            self.assertIn("scripts/build_phase2_production_source.py", text)
            self.assertIn("scripts/run_phase2_production.py", text)
            self.assertIn("${{ secrets.FUGLE_API_KEY }}", text)

    def test_runtime_scaffold_is_exact_30_no_retry_no_fallback(self):
        runtime = self.build()["candidate_files"]["src/intraday_provider_runtime.py"]
        self.assertIn("MAX_REQUESTS = 30", runtime)
        self.assertIn("MAX_RETRIES = 0", runtime)
        self.assertIn("FALLBACK_ALLOWED = False", runtime)
        self.assertIn('API_HOST = "api.fugle.tw"', runtime)
        self.assertNotIn("time.sleep(", runtime)
        self.assertNotIn("while True:", runtime)

    def test_external_plan_hash_and_preimages_are_required(self):
        with self.assertRaisesRegex(
            ActivationCandidateScaffoldError, "DELTA_PLAN_HASH_MISMATCH"
        ):
            self.build(plan_hash="f" * 64)
        delta = plan()
        first = ALLOWED_EXISTING_MUTATION_PATHS[0]
        delta["existing_file_preimage_sha256"][first] = "f" * 64
        with self.assertRaisesRegex(
            ActivationCandidateScaffoldError, "REPO_PREIMAGE_MISMATCH"
        ):
            self.build(delta=delta, plan_hash=canonical_digest(delta))

    def test_scaffold_cannot_claim_activation_or_credit(self):
        result = self.build()
        self.assertFalse(result["activation_execution_allowed"])
        self.assertFalse(result["external_dependency_resolved"])
        self.assertFalse(result["registry_activation_allowed"])
        self.assertEqual(result["production_credit"], 0)
        self.assertEqual(result["cer081_credit"], 0)
        self.assertEqual(result["network_requests"], 0)
        self.assertEqual(result["credential_access"], 0)


if __name__ == "__main__":
    unittest.main()

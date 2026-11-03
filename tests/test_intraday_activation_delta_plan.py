"""Tests for RATE intraday activation delta dry-run planning."""
from __future__ import annotations

from copy import deepcopy
import unittest

from src.intraday_activation_delta_plan import (
    ActivationDeltaPlanError,
    build_activation_delta_plan,
)
from src.intraday_activation_readiness import (
    ALLOWED_EXISTING_MUTATION_PATHS,
    repo_preimage_hashes,
)

MAIN = "1" * 40
DECISION = "CC-INTRADAY-ACTIVATION-IMPLEMENTATION-2026-11-04"


def readiness():
    return {
        "artifact": "RATE_INTRADAY_ACTIVATION_READINESS_QUALIFICATION_V1",
        "validation_status": "PASS",
        "main_sha": MAIN,
        "control_center_decision_id": "CC-READINESS",
        "permit_sha256": "2" * 64,
        "provider_authority_binding_sha256": "3" * 64,
        "payload_qualification_sha256": "4" * 64,
        "preimage_sha256": repo_preimage_hashes(),
        "allowed_existing_mutation_paths": list(ALLOWED_EXISTING_MUTATION_PATHS),
        "external_dependency_id": "EXTERNAL_AUTHORIZED_INTRADAY_FEED_DEPENDENCY",
        "source_registry_dataset_id": "authorized_market_intraday",
        "required_markets": ["TPEX", "TWSE"],
        "authorized_cadences": ["09:30", "12:00"],
        "network_requests": 0,
        "credential_access": 0,
        "registry_mutations": 0,
        "scheduler_mutations": 0,
        "production_state_mutations": 0,
        "production_credit": 0,
        "cer081_credit": 0,
        "activation_execution_allowed": False,
    }


def acceptance():
    return {
        "artifact": "RATE_INTRADAY_PROVIDER_ACCEPTANCE_V1",
        "validation_status": "PASS",
        "control_center_decision_id": "CC-PROVIDER",
        "decision_sha256": "5" * 64,
        "main_sha": MAIN,
        "provider_name": "Fugle",
        "license_basis": "OWNER_ASSUMED_AUTHORIZED",
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


class ActivationDeltaPlanTests(unittest.TestCase):
    def build(self, ready=None, accepted=None, **kwargs):
        return build_activation_delta_plan(
            ready or readiness(),
            accepted or acceptance(),
            expected_main_sha=kwargs.get("main", MAIN),
            control_center_activation_decision_id=kwargs.get("decision", DECISION),
            provider_endpoint_template=kwargs.get(
                "endpoint",
                "https://api.fugle.tw/marketdata/v1.0/stock/intraday/quote/{symbol}",
            ),
            credential_secret_name=kwargs.get("secret", "FUGLE_API_KEY"),
        )

    def test_exact_plan_is_dry_run_only(self):
        plan = self.build()
        self.assertEqual(plan["validation_status"], "PASS")
        self.assertEqual(
            plan["plan_status"],
            "READY_FOR_SEPARATE_ACTIVATION_IMPLEMENTATION_REVIEW",
        )
        self.assertFalse(plan["apply_allowed"])
        self.assertFalse(plan["activation_execution_allowed"])
        self.assertFalse(plan["external_dependency_resolved"])
        self.assertFalse(plan["registry_activation_allowed"])
        self.assertEqual(plan["production_credit"], 0)
        self.assertEqual(plan["cer081_credit"], 0)

    def test_preimages_are_recomputed_from_current_repo(self):
        plan = self.build()
        self.assertEqual(plan["existing_file_preimage_sha256"], repo_preimage_hashes())
        self.assertEqual(
            set(plan["existing_mutation_paths"]),
            set(ALLOWED_EXISTING_MUTATION_PATHS),
        )

    def test_stale_or_forged_readiness_preimage_fails(self):
        value = readiness()
        path = ALLOWED_EXISTING_MUTATION_PATHS[0]
        value["preimage_sha256"][path] = "f" * 64
        with self.assertRaisesRegex(
            ActivationDeltaPlanError, "READINESS_PREIMAGE_HASH_MISMATCH"
        ):
            self.build(ready=value)

    def test_provider_must_be_accepted_but_not_activated(self):
        value = acceptance()
        value["provider_accepted"] = False
        with self.assertRaisesRegex(
            ActivationDeltaPlanError, "PROVIDER_NOT_ACCEPTED"
        ):
            self.build(accepted=value)
        value = acceptance()
        value["activation_execution_allowed"] = True
        with self.assertRaisesRegex(
            ActivationDeltaPlanError, "PROVIDER_ACCEPTANCE_PREMATURE_STATE"
        ):
            self.build(accepted=value)

    def test_fugle_endpoint_is_https_exact_host_and_symbol_template(self):
        for endpoint, reason in (
            ("http://api.fugle.tw/x/{symbol}", "ENDPOINT_NOT_HTTPS"),
            ("https://evil.example/x/{symbol}", "FUGLE_HOST_MISMATCH"),
            ("https://api.fugle.tw/x", "SYMBOL_TEMPLATE_REQUIRED"),
            ("https://user:pass@api.fugle.tw/x/{symbol}", "UNSAFE_COMPONENT"),
        ):
            with self.subTest(endpoint=endpoint), self.assertRaisesRegex(
                ActivationDeltaPlanError, reason
            ):
                self.build(endpoint=endpoint)

    def test_exact_seven_existing_paths_and_two_new_runtime_files(self):
        plan = self.build()
        self.assertEqual(len(plan["existing_mutation_paths"]), 7)
        self.assertEqual(set(plan["mutation_specs"]), set(plan["existing_mutation_paths"]))
        self.assertEqual(
            plan["new_runtime_files"],
            [
                "src/intraday_provider_runtime.py",
                "scripts/acquire_intraday_provider_feed.py",
            ],
        )

    def test_config_postconditions_are_provider_bound(self):
        plan = self.build()
        source = plan["mutation_specs"]["config/SOURCE_REGISTRY.json"]["required_postconditions"]
        official = plan["mutation_specs"][
            "config/RATE_PRODUCTION_OFFICIAL_SOURCE_REGISTRY_V1.json"
        ]["required_postconditions"]
        self.assertEqual(source["provider"], "Fugle")
        self.assertEqual(official["authority"], "Fugle")
        self.assertEqual(source["authorization_status"], "PASS")
        self.assertEqual(official["authorization_status"], "PASS")
        self.assertFalse(official["fallback_allowed"])

    def test_phase2_postconditions_cover_all_activation_blockers(self):
        plan = self.build()
        requirements = " ".join(
            plan["mutation_specs"]["src/phase2_production.py"]["required_postconditions"]
        )
        self.assertIn("validate_phase2_source_bundle accepts all four RATE cadences", requirements)
        self.assertIn("intraday_decision_gate_status returns PASS", requirements)
        self.assertIn("decision_from_evaluation uses intraday_decision_gate_status", requirements)
        self.assertIn("validate_transition enforces the same cadence-derived intraday gate status", requirements)
        self.assertIn("authoritative admission replay", requirements)

    def test_workflow_postconditions_keep_secret_and_retry_boundaries(self):
        plan = self.build()
        for path in (
            ".github/workflows/rate_production_0930_scheduler.yml",
            ".github/workflows/rate_production_1200_scheduler.yml",
        ):
            requirements = " ".join(plan["mutation_specs"][path]["required_postconditions"])
            self.assertIn("credential injected only", requirements)
            self.assertIn("no secret output", requirements)
            self.assertIn("no automatic retry", requirements)

    def test_main_and_decision_id_are_external_bindings(self):
        with self.assertRaisesRegex(
            ActivationDeltaPlanError, "READINESS_MAIN_MISMATCH"
        ):
            self.build(main="a" * 40)
        with self.assertRaisesRegex(
            ActivationDeltaPlanError, "DECISION_ID_MISSING"
        ):
            self.build(decision="")

    def test_plan_does_not_mutate_inputs_or_repository(self):
        ready = readiness()
        accepted = acceptance()
        before_ready = deepcopy(ready)
        before_accepted = deepcopy(accepted)
        before_repo = repo_preimage_hashes()
        self.build(ready=ready, accepted=accepted)
        self.assertEqual(ready, before_ready)
        self.assertEqual(accepted, before_accepted)
        self.assertEqual(repo_preimage_hashes(), before_repo)


if __name__ == "__main__":
    unittest.main()

"""Synthetic tests for the pure RATE intraday activation-readiness gate."""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import hashlib
import unittest

from src.intraday_activation_readiness import (
    ALLOWED_EXISTING_MUTATION_PATHS,
    ActivationReadinessError,
    repo_preimage_hashes,
    validate_activation_readiness,
)

MAIN = "1" * 40
DECISION = "CC-INTRADAY-ACTIVATION-READINESS-2026-11-03"
PERMIT = "2" * 64
PROVIDER = "3" * 64
PAYLOAD = "4" * 64


def package():
    return {
        "artifact": "RATE_INTRADAY_ACTIVATION_READINESS_PACKAGE_V1",
        "status": "ENGINEERING_READINESS_ONLY",
        "activation_execution_status": "NOT_AUTHORIZED",
        "control_center_decision_id": DECISION,
        "main_sha": MAIN,
        "fallback_allowed": False,
        "automatic_retry_allowed": False,
        "production_credit_before_activation": 0,
        "cer081_credit_before_activation": 0,
        "allowed_existing_mutation_paths": list(ALLOWED_EXISTING_MUTATION_PATHS),
        "preimage_sha256": repo_preimage_hashes(),
        "target": {
            "external_dependency_id": "EXTERNAL_AUTHORIZED_INTRADAY_FEED_DEPENDENCY",
            "source_registry_dataset_id": "authorized_market_intraday",
            "required_markets": ["TWSE", "TPEX"],
            "authorized_cadences": ["09:30", "12:00"],
            "fallback_allowed": False,
            "automatic_retry_allowed": False,
        },
        "permit_qualification": {
            "artifact": "RATE_INTRADAY_ACTIVATION_PERMIT_QUALIFICATION_V1",
            "validation_status": "PASS",
            "control_center_decision_id": DECISION,
            "permit_sha256": PERMIT,
            "main_sha": MAIN,
            "required_markets": ["TPEX", "TWSE"],
            "authorized_cadences": ["09:30", "12:00"],
            "network_requests": 0,
            "credential_access": 0,
            "registry_mutations": 0,
            "scheduler_mutations": 0,
            "production_state_mutations": 0,
            "cer081_credit": 0,
            "activation_execution_status": "NOT_EXECUTED_BY_VALIDATOR",
        },
        "provider_authority_qualification": {
            "artifact": "RATE_INTRADAY_PROVIDER_AUTHORITY_QUALIFICATION_V1",
            "validation_status": "PASS",
            "authority_binding_sha256": PROVIDER,
            "required_markets": ["TPEX", "TWSE"],
            "market_coverage": ["TPEX", "TWSE"],
            "automated_non_display_use": True,
            "internal_use_only": True,
            "fallback_allowed": False,
            "credential_store": "GITHUB_ACTIONS_SECRET",
            "credential_secret_name": "RATE_INTRADAY_PROVIDER_TOKEN",
            "credential_access": 0,
            "network_requests": 0,
            "registry_mutations": 0,
            "production_activation_allowed": False,
        },
        "payload_qualification": {
            "artifact": "RATE_AUTHORIZED_TAIWAN_INTRADAY_PAYLOAD_QUALIFICATION_V1",
            "validation_status": "PASS",
            "sha256": PAYLOAD,
            "expected_count": 30,
            "selected_count": 30,
            "coverage": "30/30",
            "expected_market_counts": {"TWSE": 25, "TPEX": 5},
            "selected_market_counts": {"TWSE": 25, "TPEX": 5},
            "licensed_markets": ["TWSE", "TPEX"],
            "fallback_used": False,
            "network_requests": 0,
            "credential_access": 0,
            "production_eligible": False,
            "registry_activated": False,
        },
        "credential_boundary": {
            "store": "GITHUB_ACTIONS_SECRET",
            "secret_name": "RATE_INTRADAY_PROVIDER_TOKEN",
            "secret_value_embedded": False,
        },
        "provider_runtime": {
            "provider_selected": False,
            "provider_name": None,
            "endpoint": None,
            "live_qualification_status": "REQUIRED_NOT_YET_BOUND",
        },
    }


class ActivationReadinessTests(unittest.TestCase):
    def qualify(self, value=None, **overrides):
        return validate_activation_readiness(
            value or package(),
            expected_main_sha=overrides.get("main", MAIN),
            expected_control_center_decision_id=overrides.get("decision", DECISION),
            expected_permit_sha256=overrides.get("permit", PERMIT),
            expected_provider_authority_binding_sha256=overrides.get("provider", PROVIDER),
            expected_payload_qualification_sha256=overrides.get("payload", PAYLOAD),
        )

    def test_exact_engineering_readiness_passes_without_activation(self):
        result = self.qualify()
        self.assertEqual(result["validation_status"], "PASS")
        self.assertFalse(result["activation_execution_allowed"])
        self.assertEqual(result["network_requests"], 0)
        self.assertEqual(result["registry_mutations"], 0)
        self.assertEqual(result["scheduler_mutations"], 0)
        self.assertEqual(result["production_credit"], 0)
        self.assertEqual(result["cer081_credit"], 0)
        self.assertEqual(result["remaining_gates"][0], "LIVE_PROVIDER_QUALIFICATION")

    def test_repo_preimages_are_rooted_in_actual_files(self):
        trusted = repo_preimage_hashes()
        self.assertEqual(set(trusted), set(ALLOWED_EXISTING_MUTATION_PATHS))
        for relative, digest in trusted.items():
            self.assertEqual(digest, hashlib.sha256((Path(__file__).resolve().parents[1] / relative).read_bytes()).hexdigest())

    def test_caller_cannot_replace_preimage_hashes(self):
        value = package()
        first = ALLOWED_EXISTING_MUTATION_PATHS[0]
        value["preimage_sha256"][first] = "f" * 64
        with self.assertRaisesRegex(ActivationReadinessError, "PREIMAGE_HASH_MISMATCH"):
            self.qualify(value)

    def test_mutation_boundary_is_exact(self):
        value = package()
        value["allowed_existing_mutation_paths"].append("config/UNAUTHORIZED.json")
        with self.assertRaisesRegex(ActivationReadinessError, "MUTATION_BOUNDARY_INVALID"):
            self.qualify(value)
        value = package()
        value["allowed_existing_mutation_paths"].pop()
        with self.assertRaisesRegex(ActivationReadinessError, "MUTATION_BOUNDARY_INVALID"):
            self.qualify(value)

    def test_external_control_center_and_main_bindings_are_required(self):
        value = package()
        value["control_center_decision_id"] = "SELF_ASSERTED"
        with self.assertRaisesRegex(ActivationReadinessError, "DECISION_BINDING_MISMATCH"):
            self.qualify(value)
        value = package()
        value["main_sha"] = "a" * 40
        with self.assertRaisesRegex(ActivationReadinessError, "MAIN_BINDING_MISMATCH"):
            self.qualify(value)

    def test_permit_provider_and_payload_identities_are_independently_bound(self):
        for section, key, replacement, reason in (
            ("permit_qualification", "permit_sha256", "a" * 64, "PERMIT_HASH_BINDING_MISMATCH"),
            ("provider_authority_qualification", "authority_binding_sha256", "b" * 64, "PROVIDER_AUTHORITY_BINDING_HASH_MISMATCH"),
            ("payload_qualification", "sha256", "c" * 64, "PAYLOAD_QUALIFICATION_HASH_MISMATCH"),
        ):
            value = package()
            value[section][key] = replacement
            with self.subTest(section=section), self.assertRaisesRegex(ActivationReadinessError, reason):
                self.qualify(value)

    def test_admission_qualifications_cannot_claim_side_effects(self):
        value = package()
        value["permit_qualification"]["registry_mutations"] = 1
        with self.assertRaisesRegex(ActivationReadinessError, "PERMIT_SIDE_EFFECT_BOUNDARY_INVALID"):
            self.qualify(value)
        value = package()
        value["provider_authority_qualification"]["network_requests"] = 1
        with self.assertRaisesRegex(ActivationReadinessError, "PROVIDER_AUTHORITY_SIDE_EFFECT_BOUNDARY_INVALID"):
            self.qualify(value)
        value = package()
        value["payload_qualification"]["production_eligible"] = True
        with self.assertRaisesRegex(ActivationReadinessError, "PAYLOAD_PREACTIVATION_BOUNDARY_INVALID"):
            self.qualify(value)

    def test_payload_coverage_and_market_counts_are_exact(self):
        value = package()
        value["payload_qualification"]["coverage"] = "29/30"
        with self.assertRaisesRegex(ActivationReadinessError, "PAYLOAD_COVERAGE_INVALID"):
            self.qualify(value)
        for invalid in (
            {"TWSE": 30, "TPEX": 0},
            {"TWSE": "25", "TPEX": 5},
            {"TWSE": True, "TPEX": 29},
        ):
            value = package()
            value["payload_qualification"]["selected_market_counts"] = invalid
            with self.subTest(invalid=invalid), self.assertRaisesRegex(
                ActivationReadinessError, "PAYLOAD_MARKET_COUNTS_INVALID"
            ):
                self.qualify(value)

    def test_target_scope_is_exact_dual_market_two_cadence(self):
        value = package()
        value["target"]["required_markets"] = ["TWSE"]
        with self.assertRaisesRegex(ActivationReadinessError, "TARGET_MARKETS_INVALID"):
            self.qualify(value)
        value = package()
        value["target"]["authorized_cadences"] = ["09:30"]
        with self.assertRaisesRegex(ActivationReadinessError, "TARGET_CADENCES_INVALID"):
            self.qualify(value)
        value = package()
        value["target"]["source_registry_dataset_id"] = "other"
        with self.assertRaisesRegex(ActivationReadinessError, "TARGET_DATASET_MISMATCH"):
            self.qualify(value)

    def test_provider_selection_or_live_pass_is_premature(self):
        value = package()
        value["provider_runtime"]["provider_selected"] = True
        value["provider_runtime"]["provider_name"] = "FUGLE"
        value["provider_runtime"]["endpoint"] = "https://api.example.invalid"
        with self.assertRaisesRegex(ActivationReadinessError, "PROVIDER_SELECTION_PREMATURE"):
            self.qualify(value)
        value = package()
        value["provider_runtime"]["live_qualification_status"] = "PASS"
        with self.assertRaisesRegex(ActivationReadinessError, "LIVE_QUALIFICATION_PREMATURE"):
            self.qualify(value)

    def test_secret_value_and_secret_name_binding_are_fail_closed(self):
        value = package()
        value["credential_boundary"]["secret_value_embedded"] = True
        with self.assertRaisesRegex(ActivationReadinessError, "SECRET_VALUE_FORBIDDEN"):
            self.qualify(value)
        value = package()
        value["credential_boundary"]["secret_name"] = "OTHER_SECRET"
        with self.assertRaisesRegex(ActivationReadinessError, "SECRET_NAME_BINDING_MISMATCH"):
            self.qualify(value)

    def test_validation_does_not_mutate_protected_preimages(self):
        before = repo_preimage_hashes()
        self.qualify()
        self.assertEqual(repo_preimage_hashes(), before)

    def test_credits_retry_and_fallback_remain_zero_or_false(self):
        for field in ("fallback_allowed", "automatic_retry_allowed"):
            value = package()
            value[field] = True
            with self.subTest(field=field), self.assertRaises(ActivationReadinessError):
                self.qualify(value)
        value = package()
        value["production_credit_before_activation"] = 1
        with self.assertRaisesRegex(ActivationReadinessError, "PREMATURE_PRODUCTION_CREDIT"):
            self.qualify(value)
        value = package()
        value["cer081_credit_before_activation"] = 1
        with self.assertRaisesRegex(ActivationReadinessError, "PREMATURE_CER081_CREDIT"):
            self.qualify(value)


if __name__ == "__main__":
    unittest.main()

"""Synthetic tests for RATE intraday provider acceptance."""
from __future__ import annotations

from copy import deepcopy
import unittest

from src.intraday_provider_acceptance import (
    ProviderAcceptanceError,
    canonical_digest,
    validate_provider_acceptance,
)

MAIN = "1" * 40
DECISION_ID = "CC-PROVIDER-ACCEPTANCE-2026-11-04"
PROVIDER = "Fugle"
LIVE = "2" * 64
AUTHORITY = "3" * 64
LICENSE = "OWNER_ASSUMED_AUTHORIZED"


def decision():
    value = {
        "artifact": "RATE_INTRADAY_PROVIDER_ACCEPTANCE_DECISION_V1",
        "status": "PROVIDER_ACCEPTANCE_AUTHORIZED",
        "control_center_decision_id": DECISION_ID,
        "main_sha": MAIN,
        "provider_name": PROVIDER,
        "license_basis": LICENSE,
        "usage_scope": {
            "personal_internal_only": True,
            "public_display": False,
            "raw_data_redistribution": False,
            "resale": False,
            "sublicensing": False,
            "third_party_market_data_feed": False,
            "provider_written_confirmation": False,
        },
        "live_review": {
            "artifact": "RATE_INTRADAY_SINGLE_LIVE_QUALIFICATION_REVIEW_V1",
            "validation_status": "PASS",
            "review_disposition": "READY_FOR_CONTROL_CENTER_PROVIDER_ACCEPTANCE",
            "sha256": LIVE,
            "provider_name": PROVIDER,
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
        },
        "provider_authority": {
            "artifact": "RATE_INTRADAY_PROVIDER_AUTHORITY_QUALIFICATION_V1",
            "validation_status": "PASS",
            "authority_binding_sha256": AUTHORITY,
            "provider_name": PROVIDER,
            "required_markets": ["TWSE", "TPEX"],
            "market_coverage": ["TPEX", "TWSE"],
            "automated_non_display_use": True,
            "internal_use_only": True,
            "fallback_allowed": False,
            "production_activation_allowed": False,
        },
        "target": {
            "external_dependency_id": "EXTERNAL_AUTHORIZED_INTRADAY_FEED_DEPENDENCY",
            "source_registry_dataset_id": "authorized_market_intraday",
            "required_markets": ["TWSE", "TPEX"],
            "authorized_cadences": ["09:30", "12:00"],
        },
        "credential_boundary": {
            "store": "GITHUB_ACTIONS_SECRET",
            "secret_name": "FUGLE_API_KEY",
            "secret_value_embedded": False,
        },
        "fallback_allowed": False,
        "automatic_retry_allowed": False,
        "activation_execution_allowed": False,
        "external_dependency_resolved": False,
        "registry_activation_allowed": False,
        "production_credit": 0,
        "cer081_credit": 0,
    }
    value["decision_sha256"] = canonical_digest(value)
    return value


class ProviderAcceptanceTests(unittest.TestCase):
    def qualify(self, value=None, **overrides):
        current = value or decision()
        return validate_provider_acceptance(
            current,
            expected_main_sha=overrides.get("main", MAIN),
            expected_control_center_decision_id=overrides.get("decision_id", DECISION_ID),
            expected_decision_sha256=overrides.get("decision_hash", current["decision_sha256"]),
            expected_provider_name=overrides.get("provider", PROVIDER),
            expected_live_review_sha256=overrides.get("live", LIVE),
            expected_provider_authority_binding_sha256=overrides.get("authority", AUTHORITY),
            expected_license_basis=overrides.get("license", LICENSE),
        )

    def reseal(self, value):
        value["decision_sha256"] = canonical_digest(value, omit={"decision_sha256"})
        return value

    def test_exact_acceptance_passes_without_activation(self):
        result = self.qualify()
        self.assertEqual(result["validation_status"], "PASS")
        self.assertTrue(result["provider_accepted"])
        self.assertFalse(result["activation_execution_allowed"])
        self.assertFalse(result["external_dependency_resolved"])
        self.assertFalse(result["registry_activation_allowed"])
        self.assertEqual(result["production_credit"], 0)
        self.assertEqual(result["cer081_credit"], 0)

    def test_decision_is_self_hashed_and_externally_bound(self):
        trusted = decision()
        value = deepcopy(trusted)
        value["credential_boundary"]["secret_name"] = "OTHER_SECRET"
        self.reseal(value)
        with self.assertRaisesRegex(ProviderAcceptanceError, "EXPECTED_DECISION_HASH_MISMATCH"):
            self.qualify(value, decision_hash=trusted["decision_sha256"])
        value = decision()
        value["provider_name"] = "OTHER"
        with self.assertRaisesRegex(ProviderAcceptanceError, "PROVIDER_MISMATCH"):
            self.qualify(value)

    def test_owner_assumed_license_is_explicit_not_provider_confirmed(self):
        value = decision()
        value["usage_scope"]["provider_written_confirmation"] = True
        self.reseal(value)
        with self.assertRaisesRegex(ProviderAcceptanceError, "LICENSE_EVIDENCE_CONTRADICTION"):
            self.qualify(value)
        with self.assertRaisesRegex(ProviderAcceptanceError, "LICENSE_BASIS_MISMATCH"):
            self.qualify(license="PROVIDER_WRITTEN_CONFIRMED")

    def test_usage_scope_forbids_display_and_redistribution(self):
        for field in (
            "public_display",
            "raw_data_redistribution",
            "resale",
            "sublicensing",
            "third_party_market_data_feed",
        ):
            value = decision()
            value["usage_scope"][field] = True
            self.reseal(value)
            with self.subTest(field=field), self.assertRaisesRegex(
                ProviderAcceptanceError, "USAGE_SCOPE_INVALID"
            ):
                self.qualify(value)

    def test_live_review_hash_and_disposition_are_required(self):
        value = decision()
        value["live_review"]["sha256"] = "a" * 64
        self.reseal(value)
        with self.assertRaisesRegex(ProviderAcceptanceError, "LIVE_REVIEW_HASH_MISMATCH"):
            self.qualify(value)
        value = decision()
        value["live_review"]["review_disposition"] = "BLOCKED"
        self.reseal(value)
        with self.assertRaisesRegex(ProviderAcceptanceError, "LIVE_REVIEW_NOT_PASS"):
            self.qualify(value)

    def test_live_review_runtime_contract_is_exact(self):
        for field, bad in (
            ("network_requests", 29),
            ("http_redirects_followed", 1),
            ("automatic_retries", 1),
            ("fallback_used", True),
            ("secret_exposure", True),
        ):
            value = decision()
            value["live_review"][field] = bad
            self.reseal(value)
            with self.subTest(field=field), self.assertRaisesRegex(
                ProviderAcceptanceError, "LIVE_REVIEW_RUNTIME_BOUNDARY_INVALID"
            ):
                self.qualify(value)

    def test_live_review_market_counts_are_exact(self):
        value = decision()
        value["live_review"]["market_counts"] = {"TWSE": 30, "TPEX": 0}
        self.reseal(value)
        with self.assertRaisesRegex(ProviderAcceptanceError, "LIVE_REVIEW_MARKET_COUNTS_INVALID"):
            self.qualify(value)

    def test_provider_authority_hash_and_usage_are_required(self):
        value = decision()
        value["provider_authority"]["authority_binding_sha256"] = "a" * 64
        self.reseal(value)
        with self.assertRaisesRegex(ProviderAcceptanceError, "AUTHORITY_HASH_MISMATCH"):
            self.qualify(value)
        value = decision()
        value["provider_authority"]["automated_non_display_use"] = False
        self.reseal(value)
        with self.assertRaisesRegex(ProviderAcceptanceError, "AUTHORITY_USAGE_BOUNDARY_INVALID"):
            self.qualify(value)

    def test_target_scope_is_exact(self):
        value = decision()
        value["target"]["authorized_cadences"] = ["09:30"]
        self.reseal(value)
        with self.assertRaisesRegex(ProviderAcceptanceError, "TARGET_CADENCES_INVALID"):
            self.qualify(value)
        value = decision()
        value["target"]["required_markets"] = ["TWSE"]
        self.reseal(value)
        with self.assertRaisesRegex(ProviderAcceptanceError, "TARGET_MARKETS_INVALID"):
            self.qualify(value)

    def test_secret_value_is_forbidden(self):
        value = decision()
        value["credential_boundary"]["secret_value_embedded"] = True
        self.reseal(value)
        with self.assertRaisesRegex(ProviderAcceptanceError, "SECRET_VALUE_FORBIDDEN"):
            self.qualify(value)

    def test_acceptance_cannot_claim_activation_or_credit(self):
        for field in ("activation_execution_allowed", "external_dependency_resolved", "registry_activation_allowed"):
            value = decision()
            value[field] = True
            self.reseal(value)
            with self.subTest(field=field), self.assertRaisesRegex(
                ProviderAcceptanceError, "PREMATURE_PRODUCTION_STATE"
            ):
                self.qualify(value)
        value = decision()
        value["production_credit"] = 1
        self.reseal(value)
        with self.assertRaisesRegex(ProviderAcceptanceError, "PREMATURE_PRODUCTION_STATE"):
            self.qualify(value)


if __name__ == "__main__":
    unittest.main()

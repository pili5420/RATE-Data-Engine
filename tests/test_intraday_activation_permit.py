"""Synthetic tests for the offline RATE intraday activation-permit validator."""
from __future__ import annotations

from copy import deepcopy
import unittest

from src.intraday_activation_permit import (
    ActivationPermitError, canonical_digest, validate_activation_permit,
)

MAIN = "1" * 40
UNIVERSE = "2" * 64
AUTHORITY = "3" * 64
PAYLOAD = "4" * 64
DECISION_ID = "CONTROL_CENTER_INTRADAY_ACTIVATION_2026_11_03"


def permit():
    value = {
        "artifact": "RATE_INTRADAY_PRODUCTION_ACTIVATION_PERMIT_V1",
        "status": "INTRADAY_PRODUCTION_ACTIVATION_AUTHORIZED",
        "control_center_decision": "PASS",
        "control_center_decision_id": DECISION_ID,
        "single_use": True,
        "fallback_allowed": False,
        "automatic_retry_allowed": False,
        "cer081_credit_before_activation": 0,
        "main_sha": MAIN,
        "external_dependency_id": "EXTERNAL_AUTHORIZED_INTRADAY_FEED_DEPENDENCY",
        "source_registry_dataset_id": "authorized_market_intraday",
        "required_markets": ["TWSE", "TPEX"],
        "authorized_cadences": ["09:30", "12:00"],
        "production_universe": {
            "count": 30,
            "sha256": UNIVERSE,
            "market_counts": {"TWSE": 25, "TPEX": 5},
        },
        "provider_authority": {
            "validation_status": "PASS",
            "sha256": AUTHORITY,
            "markets": ["TWSE", "TPEX"],
            "automated_non_display_use": True,
        },
        "payload_contract": {
            "validation_status": "PASS",
            "sha256": PAYLOAD,
            "explicit_timezone_required": True,
            "exact_symbol_market_binding": True,
            "freshness_fail_closed": True,
        },
        "credential_secret_name": "RATE_INTRADAY_PROVIDER_TOKEN",
        "credential_value_embedded": False,
    }
    value["permit_sha256"] = canonical_digest(value)
    return value


class ActivationPermitTests(unittest.TestCase):
    def qualify(self, value=None, **overrides):
        current = value or permit()
        return validate_activation_permit(
            current,
            expected_main_sha=overrides.get("main", MAIN),
            expected_universe_sha256=overrides.get("universe", UNIVERSE),
            expected_provider_authority_sha256=overrides.get("authority", AUTHORITY),
            expected_payload_contract_sha256=overrides.get("payload", PAYLOAD),
            expected_control_center_decision_id=overrides.get("decision_id", DECISION_ID),
            expected_permit_sha256=overrides.get("permit_hash", current["permit_sha256"]),
        )

    def reseal(self, value):
        value["permit_sha256"] = canonical_digest(value, omit={"permit_sha256"})
        return value

    def test_exact_synthetic_permit_qualifies_without_activation(self):
        current = permit()
        result = self.qualify(current)
        self.assertEqual(result["validation_status"], "PASS")
        self.assertEqual(result["control_center_decision_id"], DECISION_ID)
        self.assertEqual(result["permit_sha256"], current["permit_sha256"])
        self.assertEqual(result["universe_count"], 30)
        self.assertEqual(result["network_requests"], 0)
        self.assertEqual(result["registry_mutations"], 0)
        self.assertEqual(result["cer081_credit"], 0)
        self.assertEqual(result["activation_execution_status"], "NOT_EXECUTED_BY_VALIDATOR")

    def test_control_center_and_single_use_are_mandatory(self):
        value = permit()
        value["control_center_decision"] = "PENDING"
        self.reseal(value)
        with self.assertRaisesRegex(ActivationPermitError, "CONTROL_CENTER_DECISION_NOT_PASS"):
            self.qualify(value)
        value = permit()
        value["single_use"] = False
        self.reseal(value)
        with self.assertRaisesRegex(ActivationPermitError, "SINGLE_USE_REQUIRED"):
            self.qualify(value)

    def test_control_center_decision_id_is_independently_bound(self):
        value = permit()
        value["control_center_decision_id"] = "SELF_ASSERTED_OTHER_DECISION"
        self.reseal(value)
        with self.assertRaisesRegex(ActivationPermitError, "DECISION_BINDING_MISMATCH"):
            self.qualify(value)

    def test_resealed_self_issued_permit_cannot_replace_trusted_permit_identity(self):
        trusted = permit()
        value = deepcopy(trusted)
        value["credential_secret_name"] = "ATTACKER_SELECTED_SECRET"
        self.reseal(value)
        with self.assertRaisesRegex(ActivationPermitError, "EXPECTED_PERMIT_HASH_MISMATCH"):
            self.qualify(value, permit_hash=trusted["permit_sha256"])

    def test_expected_permit_hash_must_be_valid(self):
        with self.assertRaisesRegex(ActivationPermitError, "EXPECTED_PERMIT_HASH_INVALID"):
            self.qualify(permit_hash="bad")
        with self.assertRaisesRegex(ActivationPermitError, "EXPECTED_CONTROL_CENTER_DECISION_ID_MISSING"):
            self.qualify(decision_id="")

    def test_main_and_dependency_bindings_fail_closed(self):
        with self.assertRaisesRegex(ActivationPermitError, "MAIN_BINDING"):
            self.qualify(main="f" * 40)
        value = permit()
        value["external_dependency_id"] = "wrong"
        self.reseal(value)
        with self.assertRaisesRegex(ActivationPermitError, "DEPENDENCY_BINDING"):
            self.qualify(value)

    def test_exact_dual_market_and_two_cadences_required(self):
        value = permit()
        value["required_markets"] = ["TWSE"]
        self.reseal(value)
        with self.assertRaisesRegex(ActivationPermitError, "DUAL_MARKET_REQUIRED"):
            self.qualify(value)
        value = permit()
        value["authorized_cadences"] = ["09:30"]
        self.reseal(value)
        with self.assertRaisesRegex(ActivationPermitError, "CADENCE_SCOPE_INVALID"):
            self.qualify(value)

    def test_universe_is_exact_30_and_hash_bound(self):
        value = permit()
        value["production_universe"]["count"] = 29
        self.reseal(value)
        with self.assertRaisesRegex(ActivationPermitError, "UNIVERSE_COUNT_INVALID"):
            self.qualify(value)
        with self.assertRaisesRegex(ActivationPermitError, "UNIVERSE_HASH_MISMATCH"):
            self.qualify(universe="a" * 64)

    def test_universe_market_counts_must_be_exact_positive_integers(self):
        for invalid in (
            {"TWSE": 30, "TPEX": 0},
            {"TWSE": "25", "TPEX": 5},
            {"TWSE": True, "TPEX": 29},
        ):
            value = permit()
            value["production_universe"]["market_counts"] = invalid
            self.reseal(value)
            with self.subTest(invalid=invalid), self.assertRaisesRegex(
                ActivationPermitError, "UNIVERSE_MARKET_COVERAGE_INVALID"
            ):
                self.qualify(value)

    def test_provider_authority_is_hash_bound_and_non_display(self):
        with self.assertRaisesRegex(ActivationPermitError, "PROVIDER_AUTHORITY_HASH_MISMATCH"):
            self.qualify(authority="a" * 64)
        value = permit()
        value["provider_authority"]["automated_non_display_use"] = False
        self.reseal(value)
        with self.assertRaisesRegex(ActivationPermitError, "NON_DISPLAY_AUTHORITY_REQUIRED"):
            self.qualify(value)

    def test_payload_contract_requires_timezone_binding_and_freshness(self):
        with self.assertRaisesRegex(ActivationPermitError, "PAYLOAD_CONTRACT_BINDING"):
            self.qualify(payload="a" * 64)
        for key in ("explicit_timezone_required", "exact_symbol_market_binding", "freshness_fail_closed"):
            value = permit()
            value["payload_contract"][key] = False
            self.reseal(value)
            with self.subTest(key=key), self.assertRaisesRegex(
                ActivationPermitError, "PAYLOAD_GATES_INCOMPLETE"
            ):
                self.qualify(value)

    def test_fallback_retry_secret_and_premature_credit_are_forbidden(self):
        value = permit()
        value["fallback_allowed"] = True
        self.reseal(value)
        with self.assertRaisesRegex(ActivationPermitError, "FALLBACK_FORBIDDEN"):
            self.qualify(value)
        value = permit()
        value["automatic_retry_allowed"] = True
        self.reseal(value)
        with self.assertRaisesRegex(ActivationPermitError, "AUTORETRY_FORBIDDEN"):
            self.qualify(value)
        value = permit()
        value["credential_value_embedded"] = True
        self.reseal(value)
        with self.assertRaisesRegex(ActivationPermitError, "SECRET_EMBEDDED"):
            self.qualify(value)
        value = permit()
        value["cer081_credit_before_activation"] = 1
        self.reseal(value)
        with self.assertRaisesRegex(ActivationPermitError, "PREMATURE_CER081_CREDIT"):
            self.qualify(value)

    def test_any_unresealed_mutation_fails_internal_hash(self):
        value = permit()
        value["credential_secret_name"] = "OTHER_SECRET"
        with self.assertRaisesRegex(ActivationPermitError, "PERMIT_HASH_MISMATCH"):
            self.qualify(value)


if __name__ == "__main__":
    unittest.main()

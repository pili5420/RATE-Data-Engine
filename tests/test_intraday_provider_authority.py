"""Synthetic-only tests for RATE intraday provider authority qualification."""
from __future__ import annotations

from copy import deepcopy
import unittest

from src.intraday_provider_authority import ProviderAuthorityError, qualify_provider_authority

DAY = "2026-11-03"
HASH_TWSE = "a" * 64
HASH_TPEX = "b" * 64
DECISION_ID = "CONTROL_CENTER_INTRADAY_PROVIDER_AUTHORITY_2026_11_03"


def expected_binding():
    return {
        "artifact": "RATE_INTRADAY_PROVIDER_AUTHORITY_EXPECTED_BINDING_V1",
        "control_center_decision_id": DECISION_ID,
        "provider_name": "SYNTHETIC_PROVIDER",
        "service_id": "dual-market-realtime",
        "credential_secret_name": "RATE_INTRADAY_PROVIDER_TOKEN",
        "valid_from": "2026-11-01",
        "valid_through": "2027-10-31",
        "exchange_evidence": {
            "TWSE": {
                "evidence_reference": "CONTROL_CENTER_APPROVED_PRIVATE_TWSE_EVIDENCE",
                "evidence_sha256": HASH_TWSE,
            },
            "TPEX": {
                "evidence_reference": "CONTROL_CENTER_APPROVED_PRIVATE_TPEX_EVIDENCE",
                "evidence_sha256": HASH_TPEX,
            },
        },
    }


def manifest():
    def authority(market):
        expected = expected_binding()["exchange_evidence"][market]
        return {
            "contract_status": "ACTIVE",
            "real_time_trading_information": True,
            "automated_non_display_use": True,
            "internal_analysis_use": True,
            "redistribution_allowed": False,
            "contract_id": "contract-" + market.lower(),
            "evidence_reference": expected["evidence_reference"],
            "evidence_sha256": expected["evidence_sha256"],
        }

    return {
        "artifact": "RATE_AUTHORIZED_TAIWAN_INTRADAY_PROVIDER_AUTHORITY_V1",
        "control_center_approval_status": "PASS",
        "control_center_decision_id": DECISION_ID,
        "fallback_allowed": False,
        "production_activation_status": "NOT_AUTHORIZED",
        "provider": {"name": "SYNTHETIC_PROVIDER", "service_id": "dual-market-realtime"},
        "service_contract": {
            "markets": ["TWSE", "TPEX"],
            "data_class": "REAL_TIME_TRADING_INFORMATION",
            "non_display_automated_analysis": True,
            "internal_use_only": True,
            "transport": "HTTPS",
            "timestamp_timezone_explicit": True,
        },
        "credential_boundary": {
            "store": "GITHUB_ACTIONS_SECRET",
            "secret_name": "RATE_INTRADAY_PROVIDER_TOKEN",
            "secret_value_embedded": False,
            "repository_secret_material": False,
        },
        "exchange_authorizations": {"TWSE": authority("TWSE"), "TPEX": authority("TPEX")},
        "valid_from": "2026-11-01",
        "valid_through": "2027-10-31",
    }


class ProviderAuthorityTests(unittest.TestCase):
    def qualify(self, value=None, day=DAY, expected=None):
        return qualify_provider_authority(
            value or manifest(),
            trading_date=day,
            expected_binding=expected or expected_binding(),
        )

    def test_valid_dual_market_manifest_is_engineering_pass_only(self):
        result = self.qualify()
        self.assertEqual(result["validation_status"], "PASS")
        self.assertEqual(result["market_coverage"], ["TPEX", "TWSE"])
        self.assertEqual(result["control_center_decision_id"], DECISION_ID)
        self.assertEqual(len(result["authority_binding_sha256"]), 64)
        self.assertFalse(result["production_activation_allowed"])
        self.assertEqual(result["network_requests"], 0)
        self.assertEqual(result["credential_access"], 0)

    def test_missing_control_center_approval_fails_closed(self):
        value = manifest()
        value["control_center_approval_status"] = "PENDING"
        with self.assertRaisesRegex(ProviderAuthorityError, "CONTROL_CENTER_APPROVAL_NOT_PASS"):
            self.qualify(value)

    def test_control_center_decision_id_is_independently_bound(self):
        value = manifest()
        value["control_center_decision_id"] = "SELF_ASSERTED_OTHER_DECISION"
        with self.assertRaisesRegex(ProviderAuthorityError, "DECISION_BINDING_MISMATCH"):
            self.qualify(value)

    def test_provider_and_service_identity_are_independently_bound(self):
        value = manifest()
        value["provider"]["name"] = "OTHER_PROVIDER"
        with self.assertRaisesRegex(ProviderAuthorityError, "NAME_BINDING_MISMATCH"):
            self.qualify(value)
        value = manifest()
        value["provider"]["service_id"] = "other-service"
        with self.assertRaisesRegex(ProviderAuthorityError, "SERVICE_ID_BINDING_MISMATCH"):
            self.qualify(value)

    def test_both_exchange_authorizations_are_required(self):
        value = manifest()
        value["exchange_authorizations"].pop("TPEX")
        with self.assertRaisesRegex(ProviderAuthorityError, "EXCHANGE_AUTHORITY_SET_INVALID"):
            self.qualify(value)

    def test_non_display_automated_use_is_required_for_each_exchange(self):
        for market in ("TWSE", "TPEX"):
            value = manifest()
            value["exchange_authorizations"][market]["automated_non_display_use"] = False
            with self.subTest(market=market), self.assertRaisesRegex(
                ProviderAuthorityError, "NON_DISPLAY_RIGHT_MISSING"
            ):
                self.qualify(value)

    def test_service_scope_must_be_exact_dual_market_realtime(self):
        value = manifest()
        value["service_contract"]["markets"] = ["TWSE"]
        with self.assertRaisesRegex(ProviderAuthorityError, "DUAL_MARKET_COVERAGE_REQUIRED"):
            self.qualify(value)
        value = manifest()
        value["service_contract"]["data_class"] = "DELAYED_TRADING_INFORMATION"
        with self.assertRaisesRegex(ProviderAuthorityError, "DATA_CLASS_INVALID"):
            self.qualify(value)

    def test_redistribution_is_forbidden_by_this_internal_use_contract(self):
        value = manifest()
        value["exchange_authorizations"]["TWSE"]["redistribution_allowed"] = True
        with self.assertRaisesRegex(ProviderAuthorityError, "REDISTRIBUTION_BOUNDARY_INVALID"):
            self.qualify(value)

    def test_contract_evidence_hash_and_reference_are_bound_to_expected_authority(self):
        value = manifest()
        value["exchange_authorizations"]["TWSE"]["evidence_sha256"] = "c" * 64
        with self.assertRaisesRegex(ProviderAuthorityError, "EVIDENCE_HASH_MISMATCH"):
            self.qualify(value)
        value = manifest()
        value["exchange_authorizations"]["TPEX"]["evidence_reference"] = "SELF_ASSERTED_REFERENCE"
        with self.assertRaisesRegex(ProviderAuthorityError, "EVIDENCE_REFERENCE_MISMATCH"):
            self.qualify(value)

    def test_manifest_cannot_replace_identity_and_all_evidence_together(self):
        value = manifest()
        value["provider"] = {"name": "FAKE_PROVIDER", "service_id": "fake-service"}
        value["control_center_decision_id"] = "FAKE_DECISION"
        for market, digest in (("TWSE", "c" * 64), ("TPEX", "d" * 64)):
            value["exchange_authorizations"][market]["evidence_reference"] = "FAKE_" + market
            value["exchange_authorizations"][market]["evidence_sha256"] = digest
        with self.assertRaises(ProviderAuthorityError):
            self.qualify(value)

    def test_validity_window_is_bound_and_covers_target_date(self):
        value = manifest()
        value["valid_through"] = "2028-10-31"
        with self.assertRaisesRegex(ProviderAuthorityError, "VALID_THROUGH_BINDING_MISMATCH"):
            self.qualify(value)
        with self.assertRaisesRegex(ProviderAuthorityError, "OUTSIDE_VALIDITY_WINDOW"):
            self.qualify(day="2027-11-01")

    def test_secret_value_and_repo_secret_material_are_forbidden(self):
        value = manifest()
        value["credential_boundary"]["secret_value_embedded"] = True
        with self.assertRaisesRegex(ProviderAuthorityError, "SECRET_VALUE_EMBEDDED"):
            self.qualify(value)
        value = manifest()
        value["credential_boundary"]["repository_secret_material"] = True
        with self.assertRaisesRegex(ProviderAuthorityError, "REPOSITORY_SECRET_FORBIDDEN"):
            self.qualify(value)

    def test_secret_name_and_store_are_boundaries(self):
        value = manifest()
        value["credential_boundary"]["store"] = "PLAINTEXT_FILE"
        with self.assertRaisesRegex(ProviderAuthorityError, "CREDENTIAL_STORE_INVALID"):
            self.qualify(value)
        value = manifest()
        value["credential_boundary"]["secret_name"] = "OTHER_SECRET"
        with self.assertRaisesRegex(ProviderAuthorityError, "SECRET_NAME_BINDING_MISMATCH"):
            self.qualify(value)

    def test_timestamp_and_transport_contracts_are_required(self):
        value = manifest()
        value["service_contract"]["timestamp_timezone_explicit"] = False
        with self.assertRaisesRegex(ProviderAuthorityError, "TIMESTAMP_TIMEZONE_CONTRACT_REQUIRED"):
            self.qualify(value)
        value = manifest()
        value["service_contract"]["transport"] = "HTTP"
        with self.assertRaisesRegex(ProviderAuthorityError, "TRANSPORT_NOT_QUALIFIED"):
            self.qualify(value)

    def test_manifest_cannot_self_activate_production(self):
        value = manifest()
        value["production_activation_status"] = "PASS"
        with self.assertRaisesRegex(ProviderAuthorityError, "PREMATURE_PRODUCTION_ACTIVATION"):
            self.qualify(value)

    def test_expected_binding_itself_must_be_complete_and_dual_market(self):
        expected = expected_binding()
        expected["exchange_evidence"].pop("TPEX")
        with self.assertRaisesRegex(ProviderAuthorityError, "EXPECTED_EXCHANGE_EVIDENCE_SET_INVALID"):
            self.qualify(expected=expected)
        expected = expected_binding()
        expected["exchange_evidence"]["TWSE"]["evidence_sha256"] = "bad"
        with self.assertRaisesRegex(ProviderAuthorityError, "EXPECTED_TWSE_EVIDENCE_HASH_INVALID"):
            self.qualify(expected=expected)


if __name__ == "__main__":
    unittest.main()

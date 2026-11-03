"""Synthetic-only tests for RATE intraday provider authority qualification."""
from __future__ import annotations

from copy import deepcopy
import unittest

from src.intraday_provider_authority import ProviderAuthorityError, qualify_provider_authority

DAY = "2026-11-03"
HASH = "a" * 64


def manifest():
    authority = {
        "contract_status": "ACTIVE",
        "real_time_trading_information": True,
        "automated_non_display_use": True,
        "internal_analysis_use": True,
        "redistribution_allowed": False,
        "contract_id": "contract-1",
        "evidence_reference": "CONTROL_CENTER_APPROVED_PRIVATE_CONTRACT_EVIDENCE",
        "evidence_sha256": HASH,
    }
    return {
        "artifact": "RATE_AUTHORIZED_TAIWAN_INTRADAY_PROVIDER_AUTHORITY_V1",
        "control_center_approval_status": "PASS",
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
        "exchange_authorizations": {"TWSE": deepcopy(authority), "TPEX": deepcopy(authority)},
        "valid_from": "2026-11-01",
        "valid_through": "2027-10-31",
    }


class ProviderAuthorityTests(unittest.TestCase):
    def qualify(self, value=None, day=DAY):
        return qualify_provider_authority(value or manifest(), trading_date=day)

    def test_valid_dual_market_manifest_is_engineering_pass_only(self):
        result = self.qualify()
        self.assertEqual(result["validation_status"], "PASS")
        self.assertEqual(result["market_coverage"], ["TPEX", "TWSE"])
        self.assertFalse(result["production_activation_allowed"])
        self.assertEqual(result["network_requests"], 0)
        self.assertEqual(result["credential_access"], 0)

    def test_missing_control_center_approval_fails_closed(self):
        value = manifest(); value["control_center_approval_status"] = "PENDING"
        with self.assertRaisesRegex(ProviderAuthorityError, "CONTROL_CENTER_APPROVAL_NOT_PASS"):
            self.qualify(value)

    def test_both_exchange_authorizations_are_required(self):
        value = manifest(); value["exchange_authorizations"].pop("TPEX")
        with self.assertRaisesRegex(ProviderAuthorityError, "EXCHANGE_AUTHORITY_SET_INVALID"):
            self.qualify(value)

    def test_non_display_automated_use_is_required_for_each_exchange(self):
        for market in ("TWSE", "TPEX"):
            value = manifest()
            value["exchange_authorizations"][market]["automated_non_display_use"] = False
            with self.subTest(market=market), self.assertRaisesRegex(ProviderAuthorityError, "NON_DISPLAY_RIGHT_MISSING"):
                self.qualify(value)

    def test_service_scope_must_be_exact_dual_market_realtime(self):
        value = manifest(); value["service_contract"]["markets"] = ["TWSE"]
        with self.assertRaisesRegex(ProviderAuthorityError, "DUAL_MARKET_COVERAGE_REQUIRED"):
            self.qualify(value)
        value = manifest(); value["service_contract"]["data_class"] = "DELAYED_TRADING_INFORMATION"
        with self.assertRaisesRegex(ProviderAuthorityError, "DATA_CLASS_INVALID"):
            self.qualify(value)

    def test_redistribution_is_forbidden_by_this_internal_use_contract(self):
        value = manifest(); value["exchange_authorizations"]["TWSE"]["redistribution_allowed"] = True
        with self.assertRaisesRegex(ProviderAuthorityError, "REDISTRIBUTION_BOUNDARY_INVALID"):
            self.qualify(value)

    def test_contract_evidence_hash_and_reference_are_required(self):
        value = manifest(); value["exchange_authorizations"]["TWSE"]["evidence_sha256"] = "bad"
        with self.assertRaisesRegex(ProviderAuthorityError, "EVIDENCE_HASH_INVALID"):
            self.qualify(value)
        value = manifest(); value["exchange_authorizations"]["TPEX"]["evidence_reference"] = ""
        with self.assertRaisesRegex(ProviderAuthorityError, "EVIDENCE_REFERENCE_MISSING"):
            self.qualify(value)

    def test_validity_window_binds_target_trading_date(self):
        with self.assertRaisesRegex(ProviderAuthorityError, "OUTSIDE_VALIDITY_WINDOW"):
            self.qualify(day="2027-11-01")

    def test_secret_value_and_repo_secret_material_are_forbidden(self):
        value = manifest(); value["credential_boundary"]["secret_value_embedded"] = True
        with self.assertRaisesRegex(ProviderAuthorityError, "SECRET_VALUE_EMBEDDED"):
            self.qualify(value)
        value = manifest(); value["credential_boundary"]["repository_secret_material"] = True
        with self.assertRaisesRegex(ProviderAuthorityError, "REPOSITORY_SECRET_FORBIDDEN"):
            self.qualify(value)

    def test_only_approved_secret_stores_are_allowed(self):
        value = manifest(); value["credential_boundary"]["store"] = "PLAINTEXT_FILE"
        with self.assertRaisesRegex(ProviderAuthorityError, "CREDENTIAL_STORE_INVALID"):
            self.qualify(value)

    def test_timestamp_and_transport_contracts_are_required(self):
        value = manifest(); value["service_contract"]["timestamp_timezone_explicit"] = False
        with self.assertRaisesRegex(ProviderAuthorityError, "TIMESTAMP_TIMEZONE_CONTRACT_REQUIRED"):
            self.qualify(value)
        value = manifest(); value["service_contract"]["transport"] = "HTTP"
        with self.assertRaisesRegex(ProviderAuthorityError, "TRANSPORT_NOT_QUALIFIED"):
            self.qualify(value)

    def test_manifest_cannot_self_activate_production(self):
        value = manifest(); value["production_activation_status"] = "PASS"
        with self.assertRaisesRegex(ProviderAuthorityError, "PREMATURE_PRODUCTION_ACTIVATION"):
            self.qualify(value)


if __name__ == "__main__":
    unittest.main()

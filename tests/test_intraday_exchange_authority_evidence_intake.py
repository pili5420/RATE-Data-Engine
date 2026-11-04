from __future__ import annotations

from copy import deepcopy
import unittest

from src.intraday_exchange_authority_evidence_intake import (
    ExchangeAuthorityEvidenceIntakeError,
    build_exchange_authority_intake,
)


def evidence():
    return {
        "TWSE": {
            "evidence_reference": "PRIVATE_TWSE_AUTHORITY_2026",
            "evidence_sha256": "a" * 64,
            "private_evidence_content_embedded": False,
            "real_time_trading_information": True,
            "automated_non_display_use": True,
            "internal_analysis_use": True,
            "contract_status": "ACTIVE",
            "contract_id": "twse-contract",
        },
        "TPEX": {
            "evidence_reference": "PRIVATE_TPEX_AUTHORITY_2026",
            "evidence_sha256": "b" * 64,
            "private_evidence_content_embedded": False,
            "real_time_trading_information": True,
            "automated_non_display_use": True,
            "internal_analysis_use": True,
            "contract_status": "ACTIVE",
            "contract_id": "tpex-contract",
        },
    }


def build(value=None):
    return build_exchange_authority_intake(
        control_center_decision_id="CC_EXCHANGE_AUTHORITY_2026_11_04",
        provider_name="Fugle",
        service_id="marketdata-v1-stock-intraday-quote",
        credential_secret_name="FUGLE_API_KEY",
        valid_from="2026-11-04",
        valid_through="2027-11-03",
        exchange_evidence=value or evidence(),
    )


class ExchangeAuthorityEvidenceIntakeTests(unittest.TestCase):
    def test_valid_dual_market_metadata_builds_expected_binding_only(self):
        result = build()
        self.assertEqual(result["validation_status"], "PASS")
        self.assertEqual(set(result["exchange_evidence"]), {"TWSE", "TPEX"})
        self.assertEqual(
            result["expected_binding"]["artifact"],
            "RATE_INTRADAY_PROVIDER_AUTHORITY_EXPECTED_BINDING_V1",
        )
        self.assertEqual(len(result["expected_binding_sha256"]), 64)
        self.assertFalse(result["production_activation_allowed"])
        self.assertFalse(result["external_dependency_resolved"])
        self.assertEqual(result["private_evidence_bytes_read"], 0)
        self.assertEqual(result["network_requests"], 0)

    def test_requires_both_markets(self):
        value = evidence()
        value.pop("TPEX")
        with self.assertRaisesRegex(ExchangeAuthorityEvidenceIntakeError, "EVIDENCE_SET_INVALID"):
            build(value)

    def test_rejects_private_content_embedding(self):
        value = evidence()
        value["TWSE"]["private_evidence_content_embedded"] = True
        with self.assertRaisesRegex(ExchangeAuthorityEvidenceIntakeError, "PRIVATE_CONTENT_FORBIDDEN"):
            build(value)

    def test_requires_active_realtime_non_display_internal_scope(self):
        mutations = [
            ("real_time_trading_information", False, "REALTIME_SCOPE_UNPROVEN"),
            ("automated_non_display_use", False, "NON_DISPLAY_SCOPE_UNPROVEN"),
            ("internal_analysis_use", False, "INTERNAL_ANALYSIS_SCOPE_UNPROVEN"),
            ("contract_status", "PENDING", "CONTRACT_NOT_ACTIVE"),
        ]
        for field, value_set, reason in mutations:
            value = evidence()
            value["TPEX"][field] = value_set
            with self.subTest(field=field), self.assertRaisesRegex(
                ExchangeAuthorityEvidenceIntakeError, reason
            ):
                build(value)

    def test_hashes_must_be_sha256(self):
        value = evidence()
        value["TWSE"]["evidence_sha256"] = "bad"
        with self.assertRaisesRegex(ExchangeAuthorityEvidenceIntakeError, "HASH_INVALID"):
            build(value)

    def test_validity_window_fails_closed(self):
        with self.assertRaisesRegex(ExchangeAuthorityEvidenceIntakeError, "VALIDITY_WINDOW_INVALID"):
            build_exchange_authority_intake(
                control_center_decision_id="x",
                provider_name="Fugle",
                service_id="svc",
                credential_secret_name="FUGLE_API_KEY",
                valid_from="2027-01-01",
                valid_through="2026-01-01",
                exchange_evidence=evidence(),
            )

    def test_self_asserted_partial_scope_cannot_pass(self):
        value = deepcopy(evidence())
        value["TWSE"]["automated_non_display_use"] = False
        value["TWSE"]["evidence_reference"] = "SELF_ASSERTED"
        value["TWSE"]["evidence_sha256"] = "c" * 64
        with self.assertRaises(ExchangeAuthorityEvidenceIntakeError):
            build(value)


if __name__ == "__main__":
    unittest.main()

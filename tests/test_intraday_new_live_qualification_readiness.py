from __future__ import annotations

from copy import deepcopy
import unittest

from src.intraday_new_live_qualification_readiness import (
    NewLiveQualificationReadinessError,
    validate_new_live_qualification_readiness,
)

MAIN = "a" * 40
BINDING = "b" * 64


def provider_confirmation():
    return {
        "provider": "Fugle",
        "provider_license_basis": "PROVIDER_WRITTEN_CONFIRMED",
        "provider_confirmed_scope": {
            "personal_internal_only": True,
            "single_user_only": True,
            "automated_non_display_analysis": True,
            "approximately_30_requests_per_cadence_allowed": True,
        },
        "previous_single_use_live_permit_reusable": False,
        "new_live_qualification_requires_fresh_control_center_authorization": True,
    }


def exchange_intake():
    return {
        "artifact": "RATE_INTRADAY_EXCHANGE_AUTHORITY_EVIDENCE_INTAKE_V1",
        "validation_status": "PASS",
        "exchange_evidence": {"TWSE": {}, "TPEX": {}},
        "private_evidence_bytes_read": 0,
        "expected_binding_sha256": BINDING,
    }


def provider_authority():
    return {
        "artifact": "RATE_INTRADAY_PROVIDER_AUTHORITY_QUALIFICATION_V1",
        "validation_status": "PASS",
        "provider_name": "Fugle",
        "market_coverage": ["TWSE", "TPEX"],
        "automated_non_display_use": True,
        "internal_use_only": True,
        "fallback_allowed": False,
        "production_activation_allowed": False,
        "authority_binding_sha256": BINDING,
    }


class NewLiveQualificationReadinessTests(unittest.TestCase):
    def test_all_gates_pass_returns_authorization_readiness_only(self):
        result = validate_new_live_qualification_readiness(
            main_sha=MAIN,
            provider_confirmation=provider_confirmation(),
            exchange_intake=exchange_intake(),
            provider_authority=provider_authority(),
        )
        self.assertEqual(
            result["readiness_disposition"],
            "READY_FOR_CONTROL_CENTER_NEW_SINGLE_LIVE_AUTHORIZATION",
        )
        self.assertEqual(result["live_requests_authorized_by_this_gate"], 0)
        self.assertFalse(result["production_activation_allowed"])
        self.assertFalse(result["external_dependency_resolved"])

    def test_provider_written_confirmation_required(self):
        value = provider_confirmation()
        value["provider_license_basis"] = "OWNER_ASSUMED_AUTHORIZED"
        with self.assertRaisesRegex(NewLiveQualificationReadinessError, "WRITTEN_CONFIRMATION_REQUIRED"):
            validate_new_live_qualification_readiness(
                main_sha=MAIN,
                provider_confirmation=value,
                exchange_intake=exchange_intake(),
                provider_authority=provider_authority(),
            )

    def test_exchange_intake_must_pass(self):
        value = exchange_intake()
        value["validation_status"] = "BLOCKED"
        with self.assertRaisesRegex(NewLiveQualificationReadinessError, "EXCHANGE_INTAKE_NOT_PASS"):
            validate_new_live_qualification_readiness(
                main_sha=MAIN,
                provider_confirmation=provider_confirmation(),
                exchange_intake=value,
                provider_authority=provider_authority(),
            )

    def test_provider_authority_must_pass(self):
        value = provider_authority()
        value["validation_status"] = "BLOCKED"
        with self.assertRaisesRegex(NewLiveQualificationReadinessError, "PROVIDER_AUTHORITY_NOT_PASS"):
            validate_new_live_qualification_readiness(
                main_sha=MAIN,
                provider_confirmation=provider_confirmation(),
                exchange_intake=exchange_intake(),
                provider_authority=value,
            )

    def test_binding_hash_must_match(self):
        value = provider_authority()
        value["authority_binding_sha256"] = "c" * 64
        with self.assertRaisesRegex(NewLiveQualificationReadinessError, "AUTHORITY_BINDING_MISMATCH"):
            validate_new_live_qualification_readiness(
                main_sha=MAIN,
                provider_confirmation=provider_confirmation(),
                exchange_intake=exchange_intake(),
                provider_authority=value,
            )

    def test_old_single_use_permit_cannot_be_reused(self):
        value = provider_confirmation()
        value["previous_single_use_live_permit_reusable"] = True
        with self.assertRaisesRegex(NewLiveQualificationReadinessError, "PREVIOUS_PERMIT_MUST_NOT_BE_REUSED"):
            validate_new_live_qualification_readiness(
                main_sha=MAIN,
                provider_confirmation=value,
                exchange_intake=exchange_intake(),
                provider_authority=provider_authority(),
            )


if __name__ == "__main__":
    unittest.main()

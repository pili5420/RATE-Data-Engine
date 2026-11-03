"""Tests for deterministic provider-acceptance decision packaging."""
from __future__ import annotations

from copy import deepcopy
import unittest

from src.intraday_provider_acceptance import validate_provider_acceptance
from src.intraday_provider_acceptance_decision import (
    ProviderAcceptanceDecisionBuildError,
    build_provider_acceptance_decision,
)

MAIN = "1" * 40
DECISION_ID = "CC-PROVIDER-ACCEPTANCE-2026-11-04"
PROVIDER = "Fugle"
AUTHORITY_HASH = "2" * 64


def live_review():
    return {
        "artifact": "RATE_INTRADAY_SINGLE_LIVE_QUALIFICATION_REVIEW_V1",
        "validation_status": "PASS",
        "review_disposition": "READY_FOR_CONTROL_CENTER_PROVIDER_ACCEPTANCE",
        "engineering_source_sha": "3" * 40,
        "trigger_commit_sha": "4" * 40,
        "workflow_run_id": 12345,
        "workflow_job_id": 67890,
        "provider_name": PROVIDER,
        "trading_date": "2026-11-04",
        "cadence": "09:30",
        "result_sha256": "5" * 64,
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


def provider_authority():
    return {
        "artifact": "RATE_INTRADAY_PROVIDER_AUTHORITY_QUALIFICATION_V1",
        "validation_status": "PASS",
        "authority_binding_sha256": AUTHORITY_HASH,
        "provider_name": PROVIDER,
        "service_id": "fugle-marketdata-rest",
        "required_markets": ["TPEX", "TWSE"],
        "market_coverage": ["TPEX", "TWSE"],
        "automated_non_display_use": True,
        "internal_use_only": True,
        "fallback_allowed": False,
        "credential_store": "GITHUB_ACTIONS_SECRET",
        "credential_secret_name": "FUGLE_API_KEY",
        "credential_access": 0,
        "network_requests": 0,
        "provider_selected_by_module": False,
        "registry_mutations": 0,
        "production_activation_allowed": False,
    }


class ProviderAcceptanceDecisionBuildTests(unittest.TestCase):
    def build(self, review=None, authority=None, **kwargs):
        return build_provider_acceptance_decision(
            review or live_review(),
            authority or provider_authority(),
            main_sha=kwargs.get("main", MAIN),
            control_center_decision_id=kwargs.get("decision_id", DECISION_ID),
            control_center_authorization_status=kwargs.get(
                "authorization_status", "PROVIDER_ACCEPTANCE_AUTHORIZED"
            ),
            provider_name=kwargs.get("provider", PROVIDER),
            license_basis=kwargs.get("license_basis", "OWNER_ASSUMED_AUTHORIZED"),
            provider_written_confirmation=kwargs.get("written", False),
            credential_secret_name=kwargs.get("secret_name", "FUGLE_API_KEY"),
        )

    def test_exact_package_is_directly_consumable_by_acceptance_validator(self):
        package = self.build()
        decision = package["decision"]
        result = validate_provider_acceptance(
            decision,
            expected_main_sha=MAIN,
            expected_control_center_decision_id=DECISION_ID,
            expected_decision_sha256=package["decision_sha256"],
            expected_provider_name=PROVIDER,
            expected_live_review_sha256=package["live_review_sha256"],
            expected_provider_authority_binding_sha256=AUTHORITY_HASH,
            expected_license_basis="OWNER_ASSUMED_AUTHORIZED",
        )
        self.assertEqual(result["validation_status"], "PASS")
        self.assertTrue(result["provider_accepted"])
        self.assertFalse(result["activation_execution_allowed"])
        self.assertEqual(package["builder_disposition"], "NOT_A_CONTROL_CENTER_DECISION")

    def test_builder_does_not_mutate_review_or_authority(self):
        review = live_review()
        authority = provider_authority()
        before_review = deepcopy(review)
        before_authority = deepcopy(authority)
        package = self.build(review, authority)
        self.assertEqual(review, before_review)
        self.assertEqual(authority, before_authority)
        package["decision"]["live_review"]["market_coverage"] = "0/30"
        self.assertEqual(review, before_review)

    def test_owner_assumed_license_requires_no_written_confirmation(self):
        with self.assertRaisesRegex(
            ProviderAcceptanceDecisionBuildError, "LICENSE_EVIDENCE_CONTRADICTION"
        ):
            self.build(written=True)

    def test_written_confirmed_license_requires_confirmation_flag(self):
        package = self.build(
            license_basis="PROVIDER_WRITTEN_CONFIRMED",
            written=True,
        )
        self.assertTrue(
            package["decision"]["usage_scope"]["provider_written_confirmation"]
        )
        with self.assertRaisesRegex(
            ProviderAcceptanceDecisionBuildError, "LICENSE_EVIDENCE_CONTRADICTION"
        ):
            self.build(
                license_basis="PROVIDER_WRITTEN_CONFIRMED",
                written=False,
            )

    def test_control_center_authorization_must_be_explicit(self):
        with self.assertRaisesRegex(
            ProviderAcceptanceDecisionBuildError,
            "CONTROL_CENTER_AUTHORIZATION_REQUIRED",
        ):
            self.build(authorization_status="PENDING")

    def test_review_must_be_pass_and_provider_unaccepted(self):
        review = live_review()
        review["review_disposition"] = "BLOCKED"
        with self.assertRaisesRegex(
            ProviderAcceptanceDecisionBuildError, "LIVE_REVIEW_NOT_PASS"
        ):
            self.build(review=review)
        review = live_review()
        review["provider_accepted"] = True
        with self.assertRaisesRegex(
            ProviderAcceptanceDecisionBuildError, "LIVE_REVIEW_PREMATURE_STATE"
        ):
            self.build(review=review)

    def test_provider_identity_is_bound_across_review_and_authority(self):
        review = live_review()
        review["provider_name"] = "OTHER"
        with self.assertRaisesRegex(
            ProviderAcceptanceDecisionBuildError, "LIVE_REVIEW_PROVIDER_MISMATCH"
        ):
            self.build(review=review)
        authority = provider_authority()
        authority["provider_name"] = "OTHER"
        with self.assertRaisesRegex(
            ProviderAcceptanceDecisionBuildError, "AUTHORITY_PROVIDER_MISMATCH"
        ):
            self.build(authority=authority)

    def test_builder_cannot_claim_activation_or_credit(self):
        package = self.build()
        decision = package["decision"]
        self.assertFalse(decision["activation_execution_allowed"])
        self.assertFalse(decision["external_dependency_resolved"])
        self.assertFalse(decision["registry_activation_allowed"])
        self.assertEqual(decision["production_credit"], 0)
        self.assertEqual(decision["cer081_credit"], 0)
        self.assertEqual(package["network_requests"], 0)
        self.assertEqual(package["registry_mutations"], 0)


if __name__ == "__main__":
    unittest.main()

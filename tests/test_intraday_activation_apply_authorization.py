"""Tests for explicit single-use activation apply authorization qualification."""
from __future__ import annotations

from copy import deepcopy
import unittest

from src.intraday_activation_apply_authorization import (
    ActivationApplyAuthorizationError,
    EXPECTED_PATHS,
    validate_activation_apply_authorization,
)
from src.intraday_activation_candidate_review import canonical_digest

MAIN = "1" * 40
MANIFEST = "2" * 64
PROVIDER = "Fugle"
DECISION = "CC-ACTIVATION-APPLY-2026-11-04"


def readiness():
    return {
        "artifact": "RATE_INTRADAY_FINAL_MAIN_ACTIVATION_APPLY_READINESS_V1",
        "validation_status": "PASS",
        "review_disposition": "READY_FOR_CONTROL_CENTER_ACTIVATION_APPLY_AUTHORIZATION",
        "current_main_sha": MAIN,
        "historical_live_binding_sha256": "3" * 64,
        "historical_candidate_base_main_sha": "4" * 40,
        "rebased_delta_plan_sha256": "5" * 64,
        "rebased_synthetic_review_sha256": "6" * 64,
        "rebased_candidate_manifest_sha256": MANIFEST,
        "provider_name": PROVIDER,
        "license_basis": "OWNER_ASSUMED_AUTHORIZED",
        "live_evidence_cadences": ["09:30"],
        "live_untested_cadences": ["12:00"],
        "current_repo_preimage_sha256": {"x": "7" * 64},
        "historical_evidence_rewritten": False,
        "provider_accepted": True,
        "apply_allowed": False,
        "activation_execution_allowed": False,
        "external_dependency_resolved": False,
        "registry_activation_allowed": False,
        "production_credit": 0,
        "cer081_credit": 0,
        "next_gate": "EXPLICIT_CONTROL_CENTER_ACTIVATION_APPLY_AUTHORIZATION",
    }


def authorization(readiness_hash):
    return {
        "artifact": "RATE_INTRADAY_ACTIVATION_APPLY_AUTHORIZATION_V1",
        "status": "ACTIVATION_APPLY_AUTHORIZED",
        "control_center_decision_id": DECISION,
        "current_main_sha": MAIN,
        "candidate_manifest_sha256": MANIFEST,
        "final_main_readiness_sha256": readiness_hash,
        "provider_name": PROVIDER,
        "single_use": True,
        "automatic_retry_allowed": False,
        "fallback_allowed": False,
        "allowed_paths": list(EXPECTED_PATHS),
        "allowed_operations": ["CREATE_OR_REPLACE_EXACT_CANDIDATE_FILES"],
        "credential_value_embedded": False,
        "live_provider_requests_allowed": 0,
        "production_credit_before_apply": 0,
        "cer081_credit_before_apply": 0,
    }


class ActivationApplyAuthorizationTests(unittest.TestCase):
    def qualify(self, auth=None, ready=None, **overrides):
        r = ready or readiness()
        r_hash = canonical_digest(r)
        a = auth or authorization(r_hash)
        return validate_activation_apply_authorization(
            a,
            r,
            expected_authorization_sha256=overrides.get("auth_hash", canonical_digest(a)),
            expected_final_main_readiness_sha256=overrides.get("ready_hash", r_hash),
            expected_current_main_sha=overrides.get("main", MAIN),
            expected_candidate_manifest_sha256=overrides.get("manifest", MANIFEST),
            expected_provider_name=overrides.get("provider", PROVIDER),
            expected_decision_id=overrides.get("decision", DECISION),
        )

    def test_exact_authorization_qualifies_without_apply(self):
        result = self.qualify()
        self.assertEqual(result["validation_status"], "PASS")
        self.assertTrue(result["authorization_valid"])
        self.assertFalse(result["apply_executed"])
        self.assertFalse(result["activation_execution_allowed_by_this_validator"])
        self.assertFalse(result["external_dependency_resolved"])
        self.assertEqual(result["repository_writes"], 0)
        self.assertEqual(result["next_gate"], "SEPARATE_SINGLE_USE_ACTIVATION_APPLY_EXECUTOR")

    def test_authorization_and_readiness_are_independently_hash_bound(self):
        with self.assertRaisesRegex(
            ActivationApplyAuthorizationError, "AUTHORIZATION_HASH_MISMATCH"
        ):
            self.qualify(auth_hash="f" * 64)
        with self.assertRaisesRegex(
            ActivationApplyAuthorizationError, "READINESS_HASH_MISMATCH"
        ):
            self.qualify(ready_hash="e" * 64)

    def test_single_use_no_retry_no_fallback_are_mandatory(self):
        r = readiness()
        rh = canonical_digest(r)
        for field, value, reason in (
            ("single_use", False, "SINGLE_USE_REQUIRED"),
            ("automatic_retry_allowed", True, "AUTORETRY_FORBIDDEN"),
            ("fallback_allowed", True, "FALLBACK_FORBIDDEN"),
        ):
            a = authorization(rh)
            a[field] = value
            with self.subTest(field=field), self.assertRaisesRegex(
                ActivationApplyAuthorizationError, reason
            ):
                self.qualify(auth=a, ready=r)

    def test_path_allowlist_is_exact(self):
        r = readiness()
        rh = canonical_digest(r)
        a = authorization(rh)
        a["allowed_paths"].append("config/UNAUTHORIZED.json")
        with self.assertRaisesRegex(
            ActivationApplyAuthorizationError, "PATH_ALLOWLIST_INVALID"
        ):
            self.qualify(auth=a, ready=r)

    def test_main_manifest_provider_and_decision_are_exact(self):
        with self.assertRaisesRegex(
            ActivationApplyAuthorizationError, "READINESS_MAIN_MISMATCH"
        ):
            self.qualify(main="f" * 40)
        with self.assertRaisesRegex(
            ActivationApplyAuthorizationError, "READINESS_MANIFEST_MISMATCH"
        ):
            self.qualify(manifest="e" * 64)
        with self.assertRaisesRegex(
            ActivationApplyAuthorizationError, "READINESS_PROVIDER_MISMATCH"
        ):
            self.qualify(provider="OTHER")
        with self.assertRaisesRegex(
            ActivationApplyAuthorizationError, "DECISION_ID_MISMATCH"
        ):
            self.qualify(decision="OTHER")

        r = readiness()
        rh = canonical_digest(r)
        a = authorization(rh)
        a["current_main_sha"] = "f" * 40
        with self.assertRaisesRegex(
            ActivationApplyAuthorizationError, "MAIN_SHA_MISMATCH"
        ):
            self.qualify(auth=a, ready=r)

        a = authorization(rh)
        a["candidate_manifest_sha256"] = "e" * 64
        with self.assertRaisesRegex(
            ActivationApplyAuthorizationError, "CANDIDATE_MANIFEST_MISMATCH"
        ):
            self.qualify(auth=a, ready=r)

        a = authorization(rh)
        a["provider_name"] = "OTHER"
        with self.assertRaisesRegex(
            ActivationApplyAuthorizationError, "PROVIDER_MISMATCH"
        ):
            self.qualify(auth=a, ready=r)

    def test_authorization_cannot_request_live_traffic_or_credit(self):
        r = readiness()
        rh = canonical_digest(r)
        a = authorization(rh)
        a["live_provider_requests_allowed"] = 1
        with self.assertRaisesRegex(
            ActivationApplyAuthorizationError, "LIVE_REQUEST_FORBIDDEN"
        ):
            self.qualify(auth=a, ready=r)
        a = authorization(rh)
        a["production_credit_before_apply"] = 1
        with self.assertRaisesRegex(
            ActivationApplyAuthorizationError, "PREMATURE_CREDIT"
        ):
            self.qualify(auth=a, ready=r)

    def test_readiness_cannot_already_claim_activation(self):
        r = readiness()
        r["activation_execution_allowed"] = True
        with self.assertRaisesRegex(
            ActivationApplyAuthorizationError, "READINESS_PREMATURE_STATE"
        ):
            self.qualify(ready=r)


if __name__ == "__main__":
    unittest.main()

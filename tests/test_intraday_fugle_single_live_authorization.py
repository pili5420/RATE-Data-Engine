from __future__ import annotations

import unittest

from src.intraday_fugle_single_live_authorization import (
    FugleSingleLiveAuthorizationError,
    canonical_digest,
    validate_fugle_single_live_authorization,
)

MAIN = "1" * 40
DECISION = "CC-FUGLE-LIVE-2026-11-04"


def readiness():
    return {
        "artifact": "RATE_INTRADAY_NEW_SINGLE_LIVE_QUALIFICATION_READINESS_V1",
        "validation_status": "PASS",
        "readiness_disposition": "READY_FOR_CONTROL_CENTER_NEW_SINGLE_LIVE_AUTHORIZATION",
        "main_sha": MAIN,
        "provider_name": "Fugle",
        "fresh_control_center_authorization_required": True,
        "previous_single_use_permit_reusable": False,
        "live_requests_authorized_by_this_gate": 0,
        "production_activation_allowed": False,
        "external_dependency_resolved": False,
        "production_credit": 0,
        "cer081_credit": 0,
    }


def authorization(readiness_hash):
    return {
        "artifact": "RATE_FUGLE_SINGLE_LIVE_QUALIFICATION_AUTHORIZATION_V1",
        "status": "FUGLE_SINGLE_LIVE_QUALIFICATION_AUTHORIZED",
        "control_center_decision_id": DECISION,
        "current_main_sha": MAIN,
        "readiness_sha256": readiness_hash,
        "provider": "Fugle",
        "cadence": "12:00",
        "request_budget": 30,
        "single_use": True,
        "execution_consumed": False,
        "automatic_retry_allowed": False,
        "fallback_allowed": False,
        "redirect_allowed": False,
        "credential_store": "GITHUB_ACTIONS_SECRET",
        "credential_secret_name": "FUGLE_API_KEY",
        "credential_value_embedded": False,
        "qualification_execution_performed": False,
        "live_requests_performed": 0,
        "credential_access": 0,
        "production_credit": 0,
        "cer081_credit": 0,
    }


class FugleSingleLiveAuthorizationTests(unittest.TestCase):
    def qualify(self, auth=None, ready=None, **overrides):
        ready = ready or readiness()
        rh = canonical_digest(ready)
        auth = auth or authorization(rh)
        return validate_fugle_single_live_authorization(
            auth,
            ready,
            expected_authorization_sha256=overrides.get("auth_hash", canonical_digest(auth)),
            expected_readiness_sha256=overrides.get("ready_hash", rh),
            expected_main_sha=overrides.get("main", MAIN),
            expected_control_center_decision_id=overrides.get("decision", DECISION),
        )

    def test_exact_authorization_passes_without_execution(self):
        result = self.qualify()
        self.assertEqual(result["validation_status"], "PASS")
        self.assertEqual(result["request_budget"], 30)
        self.assertFalse(result["qualification_execution_allowed_by_validator"])
        self.assertEqual(result["live_requests_performed"], 0)

    def test_authorization_is_bound_to_readiness_and_main(self):
        with self.assertRaisesRegex(FugleSingleLiveAuthorizationError, "READINESS_HASH_MISMATCH"):
            self.qualify(ready_hash="f" * 64)
        with self.assertRaisesRegex(FugleSingleLiveAuthorizationError, "READINESS_MAIN_MISMATCH"):
            self.qualify(main="f" * 40)

    def test_single_use_and_no_retry_boundaries_are_exact(self):
        ready = readiness()
        rh = canonical_digest(ready)
        auth = authorization(rh)
        auth["execution_consumed"] = True
        with self.assertRaisesRegex(FugleSingleLiveAuthorizationError, "SINGLE_USE_BOUNDARY_INVALID"):
            self.qualify(auth=auth, ready=ready)
        auth = authorization(rh)
        auth["automatic_retry_allowed"] = True
        with self.assertRaisesRegex(FugleSingleLiveAuthorizationError, "NETWORK_BOUNDARY_INVALID"):
            self.qualify(auth=auth, ready=ready)

    def test_request_budget_cannot_expand(self):
        ready = readiness()
        rh = canonical_digest(ready)
        auth = authorization(rh)
        auth["request_budget"] = 31
        with self.assertRaisesRegex(FugleSingleLiveAuthorizationError, "REQUEST_BUDGET_INVALID"):
            self.qualify(auth=auth, ready=ready)

    def test_secret_name_and_value_boundary_are_exact(self):
        ready = readiness()
        rh = canonical_digest(ready)
        auth = authorization(rh)
        auth["credential_secret_name"] = "OTHER"
        with self.assertRaisesRegex(FugleSingleLiveAuthorizationError, "CREDENTIAL_BOUNDARY_INVALID"):
            self.qualify(auth=auth, ready=ready)
        auth = authorization(rh)
        auth["credential_value_embedded"] = True
        with self.assertRaisesRegex(FugleSingleLiveAuthorizationError, "CREDENTIAL_BOUNDARY_INVALID"):
            self.qualify(auth=auth, ready=ready)

    def test_validator_cannot_claim_execution_or_credit(self):
        ready = readiness()
        rh = canonical_digest(ready)
        for field, bad in (
            ("qualification_execution_performed", True),
            ("live_requests_performed", 1),
            ("credential_access", 1),
            ("production_credit", 1),
            ("cer081_credit", 1),
        ):
            auth = authorization(rh)
            auth[field] = bad
            with self.subTest(field=field), self.assertRaisesRegex(
                FugleSingleLiveAuthorizationError, "PREMATURE_EXECUTION_OR_CREDIT"
            ):
                self.qualify(auth=auth, ready=ready)


if __name__ == "__main__":
    unittest.main()

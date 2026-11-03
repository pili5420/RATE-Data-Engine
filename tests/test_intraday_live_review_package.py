"""Tests for deterministic single-live review evidence packaging."""
from __future__ import annotations

from copy import deepcopy
import unittest

from src.intraday_live_review_package import (
    LiveReviewPackageError,
    build_live_review_package,
)
from src.intraday_live_qualification_review import validate_live_qualification_review

ENGINEERING = "1" * 40
TRIGGER = "2" * 40
RUN_ID = 12345
JOB_ID = 67890
BINDING = "3" * 64
DAY = "2026-11-04"
CADENCE = "09:30"
PROVIDER = "Fugle"


def universe():
    values = {f"{1000+i}": "TWSE" for i in range(25)}
    values.update({f"{2000+i}": "TPEX" for i in range(5)})
    return values


def result():
    return {
        "artifact": "RATE_FUGLE_FREE_INTRADAY_DIAGNOSTIC_RESULT_V1",
        "provider": PROVIDER,
        "plan_target": "FREE_OR_BASIC_TRIAL",
        "technical_validation_status": "PASS",
        "market_coverage": "30/30",
        "market_counts": {"TWSE": 25, "TPEX": 5},
        "trading_date": DAY,
        "cadence": CADENCE,
        "network_requests": 30,
        "http_redirects_followed": 0,
        "automatic_retries": 0,
        "fallback_used": False,
        "token_persisted": False,
        "approved_universe_binding_hash": BINDING,
        "production_eligible": False,
        "external_dependency_resolved": False,
        "registry_activation_allowed": False,
        "records": [{
            "symbol": symbol,
            "market": market,
            "timestamp_utc": "2026-11-04T01:35:00+00:00",
            "age_seconds": 30.0,
            "price": 100.0,
            "volume": 1000.0,
            "turnover": 100000.0,
        } for symbol, market in universe().items()],
    }


class LiveReviewPackageTests(unittest.TestCase):
    def build(self, value=None, **kwargs):
        return build_live_review_package(
            value or result(),
            engineering_source_sha=kwargs.get("engineering", ENGINEERING),
            trigger_commit_sha=kwargs.get("trigger", TRIGGER),
            workflow_run_id=kwargs.get("run_id", RUN_ID),
            workflow_job_id=kwargs.get("job_id", JOB_ID),
            provider_name=kwargs.get("provider", PROVIDER),
            trading_date=kwargs.get("day", DAY),
            cadence=kwargs.get("cadence", CADENCE),
            workflow_attempt=kwargs.get("attempt", 1),
            rerun_count=kwargs.get("reruns", 0),
            job_retry_count=kwargs.get("job_retries", 0),
            single_use_consumed=kwargs.get("consumed", True),
            secret_scan_status=kwargs.get("secret_scan", "PASS_NO_SECRET_EXPOSURE"),
        )

    def test_exact_package_is_directly_consumable_by_independent_review_gate(self):
        package = self.build()
        reviewed = validate_live_qualification_review(
            package,
            expected_engineering_source_sha=ENGINEERING,
            expected_trigger_commit_sha=TRIGGER,
            expected_workflow_run_id=RUN_ID,
            expected_workflow_job_id=JOB_ID,
            expected_provider_name=PROVIDER,
            expected_trading_date=DAY,
            expected_cadence=CADENCE,
            expected_result_sha256=package["result_sha256"],
            expected_universe_binding_hash=BINDING,
            expected_symbol_markets=universe(),
        )
        self.assertEqual(reviewed["validation_status"], "PASS")
        self.assertEqual(reviewed["review_disposition"], "READY_FOR_CONTROL_CENTER_PROVIDER_ACCEPTANCE")
        self.assertEqual(package["package_builder_disposition"], "NOT_A_REVIEW_DECISION")

    def test_builder_does_not_mutate_live_result(self):
        live = result()
        before = deepcopy(live)
        package = self.build(live)
        self.assertEqual(live, before)
        package["result"]["records"][0]["price"] = 999
        self.assertEqual(live, before)

    def test_workflow_identity_is_strict(self):
        for field, kwargs, reason in (
            ("engineering", {"engineering": "bad"}, "ENGINEERING_SHA_INVALID"),
            ("trigger", {"trigger": "bad"}, "TRIGGER_SHA_INVALID"),
            ("run", {"run_id": 0}, "RUN_ID_INVALID"),
            ("job", {"job_id": True}, "JOB_ID_INVALID"),
        ):
            with self.subTest(field=field), self.assertRaisesRegex(LiveReviewPackageError, reason):
                self.build(**kwargs)

    def test_single_use_and_no_retry_are_required(self):
        for kwargs, reason in (
            ({"attempt": 2}, "WORKFLOW_ATTEMPT_INVALID"),
            ({"reruns": 1}, "RETRY_FORBIDDEN"),
            ({"job_retries": 1}, "RETRY_FORBIDDEN"),
            ({"consumed": False}, "SINGLE_USE_NOT_CONSUMED"),
        ):
            with self.assertRaisesRegex(LiveReviewPackageError, reason):
                self.build(**kwargs)

    def test_secret_scan_must_pass_before_package_is_built(self):
        with self.assertRaisesRegex(LiveReviewPackageError, "SECRET_SCAN_NOT_PASS"):
            self.build(secret_scan="UNPROVEN")

    def test_provider_date_and_cadence_are_bound_to_result(self):
        for kwargs, reason in (
            ({"provider": "OTHER"}, "RESULT_PROVIDER_MISMATCH"),
            ({"day": "2026-11-05"}, "RESULT_SCOPE_MISMATCH"),
            ({"cadence": "12:00"}, "RESULT_SCOPE_MISMATCH"),
        ):
            with self.subTest(kwargs=kwargs), self.assertRaisesRegex(LiveReviewPackageError, reason):
                self.build(**kwargs)

    def test_builder_hash_changes_when_result_changes(self):
        a = self.build()
        altered = result()
        altered["records"][0]["price"] = 101.0
        b = self.build(altered)
        self.assertNotEqual(a["result_sha256"], b["result_sha256"])

    def test_builder_cannot_claim_credit_or_provider_acceptance(self):
        package = self.build()
        self.assertEqual(package["production_credit"], 0)
        self.assertEqual(package["cer081_credit"], 0)
        self.assertNotIn("provider_accepted", package)
        self.assertNotIn("activation_execution_allowed", package)


if __name__ == "__main__":
    unittest.main()

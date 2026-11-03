"""Synthetic tests for RATE single live-qualification independent review."""
from __future__ import annotations

from copy import deepcopy
import unittest

from src.intraday_live_qualification_review import (
    LiveQualificationReviewError,
    canonical_digest,
    validate_live_qualification_review,
)

ENGINEERING = "1" * 40
TRIGGER = "2" * 40
RUN_ID = 12345
JOB_ID = 67890
PROVIDER = "Fugle"
DAY = "2026-11-04"
CADENCE = "09:30"
BINDING = "3" * 64


def universe():
    result = {f"{1000+i}": "TWSE" for i in range(25)}
    result.update({f"{2000+i}": "TPEX" for i in range(5)})
    return result


def live_result():
    rows = []
    for symbol, market in universe().items():
        rows.append({
            "symbol": symbol,
            "market": market,
            "timestamp_utc": "2026-11-04T01:35:00+00:00",
            "age_seconds": 30.0,
            "price": 100.0,
            "volume": 1000,
            "turnover": 100000.0,
        })
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
        "records": rows,
    }


def package():
    result = live_result()
    return {
        "artifact": "RATE_INTRADAY_SINGLE_LIVE_QUALIFICATION_REVIEW_PACKAGE_V1",
        "review_scope": "SINGLE_LIVE_QUALIFICATION",
        "single_use_consumed": True,
        "workflow_attempt": 1,
        "rerun_count": 0,
        "job_retry_count": 0,
        "engineering_source_sha": ENGINEERING,
        "trigger_commit_sha": TRIGGER,
        "workflow_run_id": RUN_ID,
        "workflow_job_id": JOB_ID,
        "provider_name": PROVIDER,
        "trading_date": DAY,
        "cadence": CADENCE,
        "result_sha256": canonical_digest(result),
        "result": result,
        "secret_exposure": {
            "api_key_in_result": False,
            "api_key_in_logs": False,
            "raw_secret_persisted": False,
        },
        "live_provider_requests": 30,
        "fallback_used": False,
        "production_credit": 0,
        "cer081_credit": 0,
    }


class LiveQualificationReviewTests(unittest.TestCase):
    def qualify(self, value=None, **overrides):
        current = value or package()
        return validate_live_qualification_review(
            current,
            expected_engineering_source_sha=overrides.get("engineering", ENGINEERING),
            expected_trigger_commit_sha=overrides.get("trigger", TRIGGER),
            expected_workflow_run_id=overrides.get("run_id", RUN_ID),
            expected_workflow_job_id=overrides.get("job_id", JOB_ID),
            expected_provider_name=overrides.get("provider", PROVIDER),
            expected_trading_date=overrides.get("day", DAY),
            expected_cadence=overrides.get("cadence", CADENCE),
            expected_result_sha256=overrides.get("result_hash", current["result_sha256"]),
            expected_universe_binding_hash=overrides.get("binding", BINDING),
            expected_symbol_markets=overrides.get("universe", universe()),
        )

    def reseal(self, value):
        value["result_sha256"] = canonical_digest(value["result"])
        return value

    def test_exact_single_live_review_passes_only_to_control_center_acceptance(self):
        result = self.qualify()
        self.assertEqual(result["validation_status"], "PASS")
        self.assertEqual(result["review_disposition"], "READY_FOR_CONTROL_CENTER_PROVIDER_ACCEPTANCE")
        self.assertEqual(result["network_requests"], 30)
        self.assertEqual(result["market_coverage"], "30/30")
        self.assertFalse(result["provider_accepted"])
        self.assertFalse(result["activation_execution_allowed"])
        self.assertFalse(result["external_dependency_resolved"])
        self.assertEqual(result["production_credit"], 0)
        self.assertEqual(result["cer081_credit"], 0)

    def test_workflow_identity_and_single_use_are_exact(self):
        value = package()
        value["workflow_attempt"] = 2
        with self.assertRaisesRegex(LiveQualificationReviewError, "WORKFLOW_ATTEMPT_INVALID"):
            self.qualify(value)
        value = package()
        value["rerun_count"] = 1
        with self.assertRaisesRegex(LiveQualificationReviewError, "RETRY_FORBIDDEN"):
            self.qualify(value)
        value = package()
        value["trigger_commit_sha"] = "a" * 40
        with self.assertRaisesRegex(LiveQualificationReviewError, "TRIGGER_COMMIT_BINDING_MISMATCH"):
            self.qualify(value)

    def test_result_is_both_self_hashed_and_externally_bound(self):
        trusted = package()
        value = deepcopy(trusted)
        value["result"]["records"][0]["price"] = 101.0
        self.reseal(value)
        with self.assertRaisesRegex(LiveQualificationReviewError, "RESULT_EXPECTED_HASH_MISMATCH"):
            self.qualify(value, result_hash=trusted["result_sha256"])
        value = package()
        value["result"]["records"][0]["price"] = 101.0
        with self.assertRaisesRegex(LiveQualificationReviewError, "RESULT_SELF_HASH_MISMATCH"):
            self.qualify(value)

    def test_exact_30_request_budget_and_no_redirect_retry_fallback(self):
        for field, invalid, reason in (
            ("network_requests", 29, "REQUEST_COUNT_NOT_EXACT_30"),
            ("network_requests", 31, "REQUEST_COUNT_NOT_EXACT_30"),
            ("http_redirects_followed", 1, "REDIRECT_FOLLOWED"),
            ("automatic_retries", 1, "AUTOMATIC_RETRY_USED"),
            ("fallback_used", True, "FALLBACK_USED"),
            ("token_persisted", True, "TOKEN_PERSISTED"),
        ):
            value = package()
            value["result"][field] = invalid
            self.reseal(value)
            with self.subTest(field=field), self.assertRaisesRegex(
                LiveQualificationReviewError, reason
            ):
                self.qualify(value)

    def test_exact_market_counts_and_record_universe_are_required(self):
        value = package()
        value["result"]["market_counts"] = {"TWSE": 30, "TPEX": 0}
        self.reseal(value)
        with self.assertRaisesRegex(LiveQualificationReviewError, "MARKET_COUNTS_INVALID"):
            self.qualify(value)
        value = package()
        value["result"]["records"][0]["symbol"] = "9999"
        self.reseal(value)
        with self.assertRaisesRegex(LiveQualificationReviewError, "RECORD_UNIVERSE_MISMATCH"):
            self.qualify(value)
        value = package()
        value["result"]["records"][1]["symbol"] = value["result"]["records"][0]["symbol"]
        self.reseal(value)
        with self.assertRaisesRegex(LiveQualificationReviewError, "DUPLICATE_SYMBOL"):
            self.qualify(value)

    def test_record_freshness_and_numeric_contracts_fail_closed(self):
        value = package()
        value["result"]["records"][0]["age_seconds"] = 181
        self.reseal(value)
        with self.assertRaisesRegex(LiveQualificationReviewError, "FRESHNESS_FAIL"):
            self.qualify(value)
        value = package()
        value["result"]["records"][0]["price"] = 0
        self.reseal(value)
        with self.assertRaisesRegex(LiveQualificationReviewError, "PRICE_INVALID"):
            self.qualify(value)

    def test_universe_binding_hash_is_external(self):
        value = package()
        value["result"]["approved_universe_binding_hash"] = "f" * 64
        self.reseal(value)
        with self.assertRaisesRegex(LiveQualificationReviewError, "UNIVERSE_BINDING_HASH_MISMATCH"):
            self.qualify(value)

    def test_production_flags_must_remain_false(self):
        for field in ("production_eligible", "external_dependency_resolved", "registry_activation_allowed"):
            value = package()
            value["result"][field] = True
            self.reseal(value)
            with self.subTest(field=field), self.assertRaisesRegex(
                LiveQualificationReviewError, "PREMATURE_PRODUCTION_STATE"
            ):
                self.qualify(value)

    def test_secret_exposure_is_fail_closed(self):
        for field in ("api_key_in_result", "api_key_in_logs", "raw_secret_persisted"):
            value = package()
            value["secret_exposure"][field] = True
            with self.subTest(field=field), self.assertRaisesRegex(
                LiveQualificationReviewError, "SECRET_EXPOSURE_DETECTED"
            ):
                self.qualify(value)

    def test_provider_date_and_cadence_are_externally_bound(self):
        value = package()
        value["provider_name"] = "OTHER"
        with self.assertRaisesRegex(LiveQualificationReviewError, "PROVIDER_BINDING_MISMATCH"):
            self.qualify(value)
        value = package()
        value["trading_date"] = "2026-11-05"
        with self.assertRaisesRegex(LiveQualificationReviewError, "TRADING_DATE_BINDING_MISMATCH"):
            self.qualify(value)
        value = package()
        value["cadence"] = "12:00"
        with self.assertRaisesRegex(LiveQualificationReviewError, "CADENCE_BINDING_MISMATCH"):
            self.qualify(value)

    def test_package_request_count_and_credit_cannot_claim_more(self):
        value = package()
        value["live_provider_requests"] = 29
        with self.assertRaisesRegex(LiveQualificationReviewError, "PACKAGE_REQUEST_COUNT_INVALID"):
            self.qualify(value)
        value = package()
        value["production_credit"] = 1
        with self.assertRaisesRegex(LiveQualificationReviewError, "PREMATURE_CREDIT"):
            self.qualify(value)


if __name__ == "__main__":
    unittest.main()

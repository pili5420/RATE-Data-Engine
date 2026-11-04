from __future__ import annotations

import unittest

from src.intraday_fugle_execution_review_bridge import (
    FugleExecutionReviewBridgeError,
    build_review_package_from_execution,
)

ENGINEERING="1"*40
TRIGGER="2"*40


def execution():
    provider_result={
        "artifact":"RATE_FUGLE_FREE_INTRADAY_DIAGNOSTIC_RESULT_V1",
        "provider":"Fugle",
        "plan_target":"FREE_OR_BASIC_TRIAL",
        "technical_validation_status":"PASS",
        "market_coverage":"30/30",
        "market_counts":{"TWSE":25,"TPEX":5},
        "trading_date":"2026-11-04",
        "cadence":"12:00",
        "network_requests":30,
        "http_redirects_followed":0,
        "automatic_retries":0,
        "fallback_used":False,
        "token_persisted":False,
        "approved_universe_binding_hash":"3"*64,
        "production_eligible":False,
        "external_dependency_resolved":False,
        "registry_activation_allowed":False,
        "records":[],
    }
    return {
        "artifact":"RATE_FUGLE_SINGLE_LIVE_EXECUTION_RESULT_V1",
        "validation_status":"PASS",
        "authorization_review_sha256":"4"*64,
        "authorization_sha256":"5"*64,
        "current_main_sha":"6"*40,
        "provider":"Fugle",
        "trading_date":"2026-11-04",
        "cadence":"12:00",
        "fence_marker_ref":"refs/tags/rate-v11-qualification-consumed/fugle-"+"5"*32,
        "fence_marker_target_sha":"6"*40,
        "fence_readback_verified":True,
        "single_use_consumed":True,
        "github_fence_requests":3,
        "provider_network_requests":30,
        "provider_result":provider_result,
        "automatic_retries":0,
        "fallback_used":False,
        "redirects_followed":0,
        "production_activation_allowed":False,
        "external_dependency_resolved":False,
        "production_credit":0,
        "cer081_credit":0,
    }


class BridgeTests(unittest.TestCase):
    def build(self,value=None,**kw):
        return build_review_package_from_execution(
            value or execution(),
            engineering_source_sha=ENGINEERING,
            trigger_commit_sha=TRIGGER,
            workflow_run_id=kw.get("run_id",123),
            workflow_job_id=kw.get("job_id",456),
            workflow_attempt=kw.get("attempt",1),
            rerun_count=kw.get("reruns",0),
            job_retry_count=kw.get("job_retries",0),
            secret_scan_status=kw.get("secret_scan","PASS_NO_SECRET_EXPOSURE"),
        )

    def test_valid_execution_builds_bound_review_package(self):
        package=self.build()
        self.assertEqual(
            package["artifact"],
            "RATE_INTRADAY_SINGLE_LIVE_QUALIFICATION_REVIEW_PACKAGE_V1",
        )
        self.assertTrue(package["execution_binding"]["fence_readback_verified"])
        self.assertTrue(package["execution_binding"]["single_use_consumed"])
        self.assertEqual(package["execution_binding"]["provider_network_requests"],30)

    def test_unclosed_fence_fails(self):
        value=execution(); value["fence_readback_verified"]=False
        with self.assertRaisesRegex(FugleExecutionReviewBridgeError,"FENCE_NOT_CLOSED"):
            self.build(value)

    def test_provider_count_mismatch_fails(self):
        value=execution(); value["provider_network_requests"]=29
        with self.assertRaisesRegex(FugleExecutionReviewBridgeError,"PROVIDER_REQUEST_COUNT_INVALID"):
            self.build(value)

    def test_scope_mismatch_fails(self):
        value=execution(); value["provider_result"]["cadence"]="09:30"
        with self.assertRaisesRegex(FugleExecutionReviewBridgeError,"SCOPE_MISMATCH"):
            self.build(value)

    def test_retry_metadata_is_delegated_and_fails_closed(self):
        with self.assertRaises(Exception):
            self.build(reruns=1)


if __name__=="__main__":
    unittest.main()

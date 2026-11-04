from __future__ import annotations
from copy import deepcopy
import unittest

from src.intraday_fugle_live_executor_rehearsal import (
    FugleLiveExecutorRehearsalError,
    build_fugle_live_executor_rehearsal,
)

MAIN="a"*40
AUTH="b"*64


def review():
    return {
        "artifact":"RATE_FUGLE_SINGLE_LIVE_QUALIFICATION_AUTHORIZATION_QUALIFICATION_V1",
        "validation_status":"PASS",
        "authorization_sha256":AUTH,
        "current_main_sha":MAIN,
        "provider":"Fugle",
        "cadence":"12:00",
        "request_budget":30,
        "single_use":True,
        "execution_consumed":False,
        "automatic_retry_allowed":False,
        "fallback_allowed":False,
        "redirect_allowed":False,
        "credential_secret_name":"FUGLE_API_KEY",
        "qualification_execution_allowed_by_validator":False,
        "qualification_execution_performed":False,
        "live_requests_performed":0,
    }


class RehearsalTests(unittest.TestCase):
    def build(self,value=None,**kw):
        return build_fugle_live_executor_rehearsal(
            value or review(),
            expected_main_sha=kw.get("main",MAIN),
            expected_authorization_sha256=kw.get("auth",AUTH),
            trading_date=kw.get("day","2026-11-04"),
            output_name=kw.get("output","fugle-live-20261104-1200.json"),
        )

    def test_valid_review_builds_zero_io_plan(self):
        result=self.build()
        self.assertEqual(result["validation_status"],"PASS")
        self.assertEqual(result["request_budget"],30)
        self.assertEqual(result["network_requests_by_rehearsal"],0)
        self.assertEqual(result["credential_access_by_rehearsal"],0)
        self.assertFalse(result["authorization_consumed_by_rehearsal"])
        self.assertTrue(result["consumption_marker_required_before_first_network_request"])

    def test_consumed_authorization_fails(self):
        value=review(); value["execution_consumed"]=True
        with self.assertRaisesRegex(FugleLiveExecutorRehearsalError,"SINGLE_USE_INVALID"):
            self.build(value)

    def test_budget_cannot_expand(self):
        value=review(); value["request_budget"]=31
        with self.assertRaisesRegex(FugleLiveExecutorRehearsalError,"REQUEST_BUDGET_INVALID"):
            self.build(value)

    def test_network_boundaries_cannot_relax(self):
        for field in ("automatic_retry_allowed","fallback_allowed","redirect_allowed"):
            value=review(); value[field]=True
            with self.subTest(field=field), self.assertRaisesRegex(
                FugleLiveExecutorRehearsalError,"NETWORK_BOUNDARY_INVALID"):
                self.build(value)

    def test_auth_and_main_are_exact(self):
        with self.assertRaisesRegex(FugleLiveExecutorRehearsalError,"AUTH_HASH_MISMATCH"):
            self.build(auth="c"*64)
        with self.assertRaisesRegex(FugleLiveExecutorRehearsalError,"MAIN_SHA_MISMATCH"):
            self.build(main="d"*40)

    def test_output_must_be_basename_json(self):
        for name in ("../x.json","a/b.json","x.txt",".json"):
            with self.subTest(name=name), self.assertRaisesRegex(
                FugleLiveExecutorRehearsalError,"OUTPUT_NAME_INVALID"):
                self.build(output=name)


if __name__=="__main__":
    unittest.main()

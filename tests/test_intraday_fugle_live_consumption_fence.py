from __future__ import annotations
import unittest

from src.intraday_fugle_live_consumption_fence import (
    AmbiguousFenceWrite,
    FugleConsumptionFenceError,
    SyntheticWriteOnceFenceStore,
    canonical_digest,
    consume_fugle_single_live_fence,
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
    }


class FenceTests(unittest.TestCase):
    def consume(self, store=None, value=None, **kw):
        value=value or review()
        return consume_fugle_single_live_fence(
            value,
            store or SyntheticWriteOnceFenceStore(),
            expected_authorization_review_sha256=kw.get("hash",canonical_digest(value)),
            expected_main_sha=kw.get("main",MAIN),
        )

    def test_create_and_readback_passes(self):
        result=self.consume()
        self.assertEqual(result["validation_status"],"PASS")
        self.assertTrue(result["readback_verified"])
        self.assertEqual(result["credential_access_before_receipt"],0)
        self.assertEqual(result["provider_requests_before_receipt"],0)

    def test_ambiguous_after_create_is_resolved_by_readback(self):
        store=SyntheticWriteOnceFenceStore(fail_mode="AMBIGUOUS_AFTER_CREATE")
        result=self.consume(store=store)
        self.assertEqual(result["outcome"],"AMBIGUOUS_CREATE_CONFIRMED_BY_READBACK")
        self.assertEqual(result["write_attempts"],1)

    def test_reentry_is_blocked(self):
        store=SyntheticWriteOnceFenceStore()
        self.consume(store=store)
        with self.assertRaisesRegex(FugleConsumptionFenceError,"ALREADY_CONSUMED"):
            self.consume(store=store)

    def test_main_drift_fails(self):
        with self.assertRaisesRegex(FugleConsumptionFenceError,"MAIN_BINDING_MISMATCH"):
            self.consume(main="c"*40)

    def test_relaxed_network_policy_fails(self):
        value=review(); value["automatic_retry_allowed"]=True
        with self.assertRaisesRegex(FugleConsumptionFenceError,"NETWORK_BOUNDARY_INVALID"):
            self.consume(value=value)


if __name__=="__main__":
    unittest.main()

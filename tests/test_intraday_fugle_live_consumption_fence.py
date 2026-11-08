from __future__ import annotations
from concurrent.futures import ThreadPoolExecutor
import threading
import unittest
from unittest.mock import patch

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
        self.assertTrue(result["executor_ownership_verified"])
        self.assertEqual(result["credential_access_before_receipt"],0)
        self.assertEqual(result["provider_requests_before_receipt"],0)

    def test_ambiguous_after_create_burns_permit_and_never_grants_ownership(self):
        store=SyntheticWriteOnceFenceStore(fail_mode="AMBIGUOUS_AFTER_CREATE")
        with self.assertRaisesRegex(FugleConsumptionFenceError,"EXCLUSIVE_CREATE_NOT_ACKNOWLEDGED"):
            self.consume(store=store)
        self.assertEqual(store.write_attempts,1)
        self.assertEqual(store.read_attempts,1)
        self.assertEqual(len(store.values),1)
        with self.assertRaisesRegex(FugleConsumptionFenceError,"ALREADY_CONSUMED"):
            self.consume(store=store)

    def test_concurrent_exclusive_create_proves_at_most_one_owner(self):
        for lose_ack in (False,True):
            with self.subTest(lose_ack=lose_ack):
                store=SyntheticWriteOnceFenceStore(
                    fail_mode="AMBIGUOUS_AFTER_CREATE" if lose_ack else None
                )
                barrier=threading.Barrier(2)
                read=store.read

                def simultaneous_read(key):
                    value=read(key)
                    if value is None:
                        barrier.wait(timeout=5)
                    return value

                def attempt():
                    try:
                        return self.consume(store=store)
                    except FugleConsumptionFenceError as exc:
                        return str(exc)

                with patch.object(store,"read",side_effect=simultaneous_read), \
                        ThreadPoolExecutor(max_workers=2) as workers:
                    futures=[workers.submit(attempt) for _ in range(2)]
                    results=[future.result(timeout=10) for future in futures]
                owners=[result for result in results if isinstance(result,dict)]
                self.assertEqual(len(owners),0 if lose_ack else 1)
                self.assertEqual(store.write_attempts,2)
                self.assertEqual(len(store.values),1)

    def test_unknown_create_acknowledgement_fails_closed(self):
        store=SyntheticWriteOnceFenceStore()
        with patch.object(store,"create_once",return_value=None):
            with self.assertRaisesRegex(FugleConsumptionFenceError,"EXCLUSIVE_CREATE_NOT_ACKNOWLEDGED"):
                self.consume(store=store)
        self.assertEqual(store.read_attempts,1)

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

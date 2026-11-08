from __future__ import annotations
import unittest

from src.intraday_fugle_live_consumption_fence import (
    SyntheticWriteOnceFenceStore,
    FugleConsumptionFenceError,
    canonical_digest,
)
from src.intraday_fugle_live_executor_orchestration import (
    FugleLiveExecutorOrchestrationError,
    SyntheticFugleExecutorBackend,
    rehearse_fugle_fence_then_execute,
)

MAIN="a"*40
AUTH="b"*64

def review():
    return {
        "artifact":"RATE_FUGLE_SINGLE_LIVE_QUALIFICATION_AUTHORIZATION_QUALIFICATION_V1",
        "validation_status":"PASS",
        "authorization_sha256":AUTH,
        "readiness_sha256":"c"*64,
        "current_main_sha":MAIN,
        "control_center_decision_id":"CC-FUGLE-LIVE",
        "provider":"Fugle",
        "cadence":"12:00",
        "request_budget":30,
        "single_use":True,
        "execution_consumed":False,
        "automatic_retry_allowed":False,
        "fallback_allowed":False,
        "redirect_allowed":False,
        "credential_store":"GITHUB_ACTIONS_SECRET",
        "credential_secret_name":"FUGLE_API_KEY",
        "qualification_execution_allowed_by_validator":False,
        "qualification_execution_performed":False,
        "live_requests_performed":0,
        "credential_access":0,
        "production_activation_allowed":False,
        "external_dependency_resolved":False,
        "production_credit":0,
        "cer081_credit":0,
        "next_gate":"SEPARATE_FUGLE_SINGLE_LIVE_QUALIFICATION_EXECUTOR",
    }


class OrchestrationTests(unittest.TestCase):
    def execute(self, backend=None, store=None):
        value=review()
        return rehearse_fugle_fence_then_execute(
            value,
            store or SyntheticWriteOnceFenceStore(),
            backend or SyntheticFugleExecutorBackend(),
            expected_authorization_review_sha256=canonical_digest(value),
            expected_main_sha=MAIN,
            trading_date="2026-11-04",
            output_name="fugle-live-20261104-1200.json",
        )

    def test_fence_precedes_credential_and_network(self):
        result=self.execute()
        self.assertTrue(result["fence_persisted_and_readback_before_credential"])
        self.assertEqual(result["credential_reads_after_fence"],1)
        self.assertEqual(result["provider_requests_after_fence"],30)
        self.assertEqual(result["real_provider_requests"],0)

    def test_wrong_synthetic_request_count_fails_closed(self):
        with self.assertRaisesRegex(FugleLiveExecutorOrchestrationError,"REQUEST_COUNT_INVALID"):
            self.execute(backend=SyntheticFugleExecutorBackend(expected_requests=29))

    def test_reused_store_blocks_second_execution(self):
        store=SyntheticWriteOnceFenceStore()
        self.execute(store=store)
        from src.intraday_fugle_live_consumption_fence import FugleConsumptionFenceError
        with self.assertRaises(FugleConsumptionFenceError):
            self.execute(store=store)

    def test_lost_create_ack_blocks_credential_and_provider_access(self):
        backend=SyntheticFugleExecutorBackend()
        store=SyntheticWriteOnceFenceStore(fail_mode="AMBIGUOUS_AFTER_CREATE")
        with self.assertRaisesRegex(FugleConsumptionFenceError,"EXCLUSIVE_CREATE_NOT_ACKNOWLEDGED"):
            self.execute(store=store,backend=backend)
        self.assertEqual(backend.credential_reads,0)
        self.assertEqual(backend.network_requests,0)
        with self.assertRaisesRegex(FugleConsumptionFenceError,"ALREADY_CONSUMED"):
            self.execute(store=store,backend=backend)
        self.assertEqual(backend.credential_reads,0)
        self.assertEqual(backend.network_requests,0)


if __name__=="__main__":
    unittest.main()

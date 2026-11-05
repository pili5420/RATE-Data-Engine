from __future__ import annotations

from collections import OrderedDict
from datetime import datetime, timezone
import json
import unittest
from unittest.mock import Mock, patch

from src.intraday_fugle_live_consumption_fence import canonical_digest
from src.intraday_fugle_github_fence_transport import ref_name_for
from src.intraday_fugle_single_live_executor import execute_authorized_fugle_single_live
from src.authorized_intraday_feed import load_authoritative_universe_binding

MAIN="a"*40
AUTH="b"*64


def authorization_review():
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


def binding():
    trusted,lineage=load_authoritative_universe_binding()
    return {
        "artifact":"RATE_FUGLE_FREE_INTRADAY_UNIVERSE_BINDING_V1",
        "evidence_scope":"DIAGNOSTIC_ONLY",
        "validation_status":"PASS",
        "expected_count":30,
        "expected_market_counts":{"TWSE":25,"TPEX":5},
        "production_snapshot_id":lineage["production_snapshot_id"],
        "source_bundle_path":lineage["immutable_bundle_path"],
        "source_bundle_sha256":lineage["source_bundle_sha256"],
        "universe_contract_sha256":lineage["universe_contract_sha256"],
        "universe_binding_hash":lineage["universe_binding_hash"],
        "records":[{"symbol":s,"market":m} for s,m in trusted.items()],
    }


class FakeGHResponse:
    def __init__(self,status,body):
        self.status=status; self._body=body
    def read(self,n=-1): return self._body


class FakeGHConnection:
    responses=[]
    def __init__(self,*args,**kwargs): pass
    def request(self,*args,**kwargs): pass
    def getresponse(self): return self.__class__.responses.pop(0)
    def close(self): pass


class FakeFugleResponse:
    def __init__(self,body):
        self.status=200; self._body=json.dumps(body).encode()
    def read(self): return self._body


class FakeFugleConnection:
    queue=[]
    requests=0
    def __init__(self,*args,**kwargs): pass
    def request(self,*args,**kwargs): self.__class__.requests += 1
    def getresponse(self): return FakeFugleResponse(self.__class__.queue.pop(0))
    def close(self): pass


def provider_rows(day,now):
    trusted,_=load_authoritative_universe_binding()
    ts=int(now.timestamp()*1000)
    return [{
        "symbol":s,
        "exchange":m,
        "date":day,
        "lastUpdated":ts,
        "lastPrice":100.0,
        "total":{"tradeVolume":1,"tradeValue":100.0},
    } for s,m in trusted.items()]


class ExecutorTests(unittest.TestCase):
    def setUp(self):
        FakeGHConnection.responses=[]
        FakeFugleConnection.queue=[]
        FakeFugleConnection.requests=0

    @patch("src.intraday_fugle_github_fence_transport.http.client.HTTPSConnection",FakeGHConnection)
    def test_fence_then_exact_30_provider_requests(self):
        now=datetime(2026,11,4,4,0,tzinfo=timezone.utc)
        marker=json.dumps({
            "ref":ref_name_for(AUTH),
            "object":{"type":"commit","sha":MAIN},
        }).encode()
        FakeGHConnection.responses=[
            FakeGHResponse(404,b"{}"),
            FakeGHResponse(201,marker),
            FakeGHResponse(200,marker),
        ]
        FakeFugleConnection.queue=provider_rows("2026-11-04",now)
        review=authorization_review()
        result=execute_authorized_fugle_single_live(
            review,
            binding(),
            expected_authorization_review_sha256=canonical_digest(review),
            github_token="synthetic-github-token",
            fugle_api_key="synthetic-fugle-key",
            trading_date="2026-11-04",
            now_utc=now,
            fugle_connection_factory=FakeFugleConnection,
        )
        self.assertTrue(result["fence_readback_verified"])
        self.assertTrue(result["single_use_consumed"])
        self.assertEqual(result["github_fence_requests"],3)
        self.assertEqual(result["provider_network_requests"],30)
        self.assertEqual(FakeFugleConnection.requests,30)
        self.assertFalse(result["production_activation_allowed"])

    @patch("src.intraday_fugle_github_fence_transport.http.client.HTTPSConnection",FakeGHConnection)
    def test_existing_marker_blocks_before_provider_request(self):
        now=datetime(2026,11,4,4,0,tzinfo=timezone.utc)
        marker=json.dumps({
            "ref":ref_name_for(AUTH),
            "object":{"type":"commit","sha":MAIN},
        }).encode()
        FakeGHConnection.responses=[FakeGHResponse(200,marker)]
        FakeFugleConnection.queue=provider_rows("2026-11-04",now)
        review=authorization_review()
        from src.intraday_fugle_github_fence_adapter import FugleGitHubFenceAdapterError
        with self.assertRaises(FugleGitHubFenceAdapterError):
            execute_authorized_fugle_single_live(
                review,binding(),
                expected_authorization_review_sha256=canonical_digest(review),
                github_token="synthetic-github-token",
                fugle_api_key="synthetic-fugle-key",
                trading_date="2026-11-04",
                now_utc=now,
                fugle_connection_factory=FakeFugleConnection,
            )
        self.assertEqual(FakeFugleConnection.requests,0)

    @patch("src.intraday_fugle_github_fence_transport.http.client.HTTPSConnection", FakeGHConnection)
    def test_lost_ack_and_create_conflict_block_credential_loader_and_provider(self):
        from src.intraday_fugle_github_fence_adapter import FugleGitHubFenceAdapterError
        review = authorization_review()
        marker = json.dumps({"ref": ref_name_for(AUTH), "object": {"type": "commit", "sha": MAIN}}).encode()
        for status in (409, 422, 500):
            FakeGHConnection.responses = [FakeGHResponse(404, b"{}"), FakeGHResponse(status, b"{}"), FakeGHResponse(200, marker)]
            with self.subTest(status=status), patch(
                "os.getenv", side_effect=AssertionError("No environment credential reads")
            ), patch.object(FakeFugleConnection, "__init__") as connection_mock:
                credential_loader = Mock(return_value="synthetic-fugle-key")
                with self.assertRaises(FugleGitHubFenceAdapterError):
                    execute_authorized_fugle_single_live(
                        review, binding(),
                        expected_authorization_review_sha256=canonical_digest(review),
                        github_token="synthetic-github-token",
                        fugle_credential_loader=credential_loader,
                        trading_date="2026-11-04",
                        now_utc=datetime(2026, 11, 4, 4, 0, tzinfo=timezone.utc),
                        fugle_connection_factory=FakeFugleConnection,
                    )
                credential_loader.assert_not_called()
                connection_mock.assert_not_called()
                self.assertEqual(FakeFugleConnection.requests, 0)
                self.assertEqual(len(FakeGHConnection.responses), 1)

    @patch("src.intraday_fugle_github_fence_transport.http.client.HTTPSConnection", FakeGHConnection)
    def test_credential_loader_runs_only_after_exclusive_create_and_readback(self):
        now = datetime(2026, 11, 4, 4, 0, tzinfo=timezone.utc)
        marker = json.dumps({"ref": ref_name_for(AUTH), "object": {"type": "commit", "sha": MAIN}}).encode()
        FakeGHConnection.responses = [FakeGHResponse(404, b"{}"), FakeGHResponse(201, marker), FakeGHResponse(200, marker)]
        FakeFugleConnection.queue = provider_rows("2026-11-04", now)
        reads = []

        def credential_loader():
            self.assertEqual(FakeGHConnection.responses, [])
            self.assertEqual(FakeFugleConnection.requests, 0)
            reads.append("synthetic-read")
            return "synthetic-fugle-key"

        review = authorization_review()
        result = execute_authorized_fugle_single_live(
            review, binding(), expected_authorization_review_sha256=canonical_digest(review),
            github_token="synthetic-github-token", fugle_credential_loader=credential_loader,
            trading_date="2026-11-04", now_utc=now, fugle_connection_factory=FakeFugleConnection,
        )
        self.assertEqual(reads, ["synthetic-read"])
        self.assertTrue(result["executor_ownership_verified"])
        self.assertEqual(FakeFugleConnection.requests, 30)


if __name__=="__main__":
    unittest.main()

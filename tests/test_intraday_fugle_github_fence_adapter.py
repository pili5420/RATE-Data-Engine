from __future__ import annotations
from concurrent.futures import ThreadPoolExecutor
import json
import threading
import unittest
from unittest.mock import patch

from src.intraday_fugle_github_fence_transport import (
    FugleGitHubFenceTransport, ref_name_for
)
from src.intraday_fugle_github_fence_adapter import (
    FugleGitHubFenceAdapterError, persist_consumption_marker
)

AUTH="a"*64
MAIN="b"*40


class FakeResponse:
    def __init__(self,status,body):
        self.status=status
        self._body=body
    def read(self,n=-1):
        return self._body


class FakeConnection:
    responses=[]
    requests=[]
    def __init__(self,*args,**kwargs): pass
    def request(self,method,*args,**kwargs):
        self.__class__.requests.append(method)
    def getresponse(self):
        response=self.__class__.responses.pop(0)
        if isinstance(response,Exception):
            raise response
        return response
    def close(self): pass


def marker_body():
    return json.dumps({
        "ref":ref_name_for(AUTH),
        "object":{"type":"commit","sha":MAIN},
    }).encode()


class AdapterTests(unittest.TestCase):
    def setUp(self):
        FakeConnection.responses=[]
        FakeConnection.requests=[]

    @patch("src.intraday_fugle_github_fence_transport.http.client.HTTPSConnection",FakeConnection)
    def test_create_and_readback(self):
        FakeConnection.responses=[
            FakeResponse(404,b"{}"),
            FakeResponse(201,marker_body()),
            FakeResponse(200,marker_body()),
        ]
        t=FugleGitHubFenceTransport(github_token="synthetic-token")
        result=persist_consumption_marker(t,authorization_sha256=AUTH,main_sha=MAIN)
        self.assertEqual(result["outcome"],"CREATED_AND_READBACK_VERIFIED")
        self.assertEqual(result["github_requests"],3)
        self.assertTrue(result["readback_verified"])
        self.assertTrue(result["executor_ownership_verified"])
        self.assertEqual(result["ownership_proof"],
                         "EXCLUSIVE_CREATE_ACKNOWLEDGED_IN_CURRENT_INVOCATION")

    @patch("src.intraday_fugle_github_fence_transport.http.client.HTTPSConnection",FakeConnection)
    def test_existing_marker_blocks_reentry(self):
        FakeConnection.responses=[FakeResponse(200,marker_body())]
        t=FugleGitHubFenceTransport(github_token="synthetic-token")
        with self.assertRaisesRegex(FugleGitHubFenceAdapterError,"ALREADY_CONSUMED"):
            persist_consumption_marker(t,authorization_sha256=AUTH,main_sha=MAIN)

    @patch("src.intraday_fugle_github_fence_transport.http.client.HTTPSConnection",FakeConnection)
    def test_unacknowledged_create_never_recovers_ownership_from_readback(self):
        for failed_response in (
            FakeResponse(409,b"{}"),
            FakeResponse(422,b"{}"),
            FakeResponse(500,b"{}"),
            FakeResponse(201,b"[]"),
            FakeResponse(201,b"not-json"),
            FakeResponse(201,json.dumps({
                "ref":ref_name_for("c"*64),
                "object":{"type":"commit","sha":MAIN},
            }).encode()),
            FakeResponse(201,json.dumps({
                "ref":ref_name_for(AUTH),
                "object":{"type":"commit","sha":"d"*40},
            }).encode()),
            TimeoutError("synthetic lost ACK"),
        ):
            with self.subTest(response=type(failed_response).__name__):
                FakeConnection.requests=[]
                FakeConnection.responses=[
                    FakeResponse(404,b"{}"),
                    failed_response,
                    FakeResponse(200,marker_body()),
                ]
                t=FugleGitHubFenceTransport(github_token="synthetic-token")
                with self.assertRaisesRegex(FugleGitHubFenceAdapterError,
                                            "EXCLUSIVE_CREATE_NOT_ACKNOWLEDGED"):
                    persist_consumption_marker(t,authorization_sha256=AUTH,main_sha=MAIN)
                self.assertEqual(FakeConnection.requests,["GET","POST"])
                self.assertEqual(t.request_count,2)
                self.assertEqual(len(FakeConnection.responses),1)

    def test_concurrent_create_has_one_owner_and_lost_ack_has_none(self):
        for lose_ack in (False,True):
            with self.subTest(lose_ack=lose_ack):
                barrier=threading.Barrier(2)
                lock=threading.Lock()
                state={"created":False,"posts":0}

                class AtomicConnection:
                    def __init__(self,*args,**kwargs):
                        self.response=None

                    def request(self,method,path,body=None,headers=None):
                        with lock:
                            if method=="POST":
                                state["posts"] += 1
                                if state["created"]:
                                    self.response=FakeResponse(422,b"{}")
                                else:
                                    state["created"]=True
                                    self.response=(TimeoutError("synthetic lost ACK")
                                                   if lose_ack else FakeResponse(201,marker_body()))
                            elif state["created"]:
                                self.response=FakeResponse(200,marker_body())
                            else:
                                self.response=FakeResponse(404,b"{}")
                        # Force both contenders to observe absence before either POST.
                        if method=="GET" and self.response.status==404:
                            barrier.wait(timeout=5)

                    def getresponse(self):
                        if isinstance(self.response,Exception):
                            raise self.response
                        return self.response

                    def close(self):
                        pass

                def attempt():
                    transport=FugleGitHubFenceTransport(github_token="synthetic-token")
                    try:
                        return persist_consumption_marker(
                            transport,authorization_sha256=AUTH,main_sha=MAIN
                        )
                    except FugleGitHubFenceAdapterError as exc:
                        return str(exc)

                with patch("src.intraday_fugle_github_fence_transport.http.client.HTTPSConnection",
                           AtomicConnection), ThreadPoolExecutor(max_workers=2) as workers:
                    futures=[workers.submit(attempt) for _ in range(2)]
                    results=[future.result(timeout=10) for future in futures]
                    owners=[result for result in results if isinstance(result,dict)]
                    self.assertEqual(len(owners),0 if lose_ack else 1)
                    self.assertEqual(state["posts"],2)
                    self.assertTrue(state["created"])
                    # The consumed marker blocks every subsequent invocation too.
                    with self.assertRaisesRegex(FugleGitHubFenceAdapterError,"ALREADY_CONSUMED"):
                        persist_consumption_marker(
                            FugleGitHubFenceTransport(github_token="synthetic-token"),
                            authorization_sha256=AUTH,main_sha=MAIN,
                        )
                    self.assertEqual(state["posts"],2)

    @patch("src.intraday_fugle_github_fence_transport.http.client.HTTPSConnection",FakeConnection)
    def test_unknown_readback_after_ack_fails_closed(self):
        for response in (FakeResponse(404,b"{}"),FakeResponse(500,b"{}"),
                         TimeoutError("synthetic readback failure")):
            with self.subTest(response=type(response).__name__):
                FakeConnection.responses=[FakeResponse(404,b"{}"),
                                          FakeResponse(201,marker_body()),response]
                with self.assertRaises(RuntimeError):
                    persist_consumption_marker(
                        FugleGitHubFenceTransport(github_token="synthetic-token"),
                        authorization_sha256=AUTH,main_sha=MAIN,
                    )


if __name__=="__main__":
    unittest.main()

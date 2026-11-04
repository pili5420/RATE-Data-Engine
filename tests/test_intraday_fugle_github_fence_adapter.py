from __future__ import annotations
import json
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
    def __init__(self,*args,**kwargs): pass
    def request(self,*args,**kwargs): pass
    def getresponse(self): return self.__class__.responses.pop(0)
    def close(self): pass


def marker_body():
    return json.dumps({
        "ref":ref_name_for(AUTH),
        "object":{"type":"commit","sha":MAIN},
    }).encode()


class AdapterTests(unittest.TestCase):
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

    @patch("src.intraday_fugle_github_fence_transport.http.client.HTTPSConnection",FakeConnection)
    def test_existing_marker_blocks_reentry(self):
        FakeConnection.responses=[FakeResponse(200,marker_body())]
        t=FugleGitHubFenceTransport(github_token="synthetic-token")
        with self.assertRaisesRegex(FugleGitHubFenceAdapterError,"ALREADY_CONSUMED"):
            persist_consumption_marker(t,authorization_sha256=AUTH,main_sha=MAIN)

    @patch("src.intraday_fugle_github_fence_transport.http.client.HTTPSConnection",FakeConnection)
    def test_ambiguous_create_is_readback_only_no_retry(self):
        FakeConnection.responses=[
            FakeResponse(404,b"{}"),
            FakeResponse(500,b"{}"),
            FakeResponse(200,marker_body()),
        ]
        t=FugleGitHubFenceTransport(github_token="synthetic-token")
        result=persist_consumption_marker(t,authorization_sha256=AUTH,main_sha=MAIN)
        self.assertEqual(result["outcome"],"AMBIGUOUS_CREATE_CONFIRMED_BY_READBACK")
        self.assertEqual(result["github_requests"],3)
        self.assertEqual(result["create_retries"],0)


if __name__=="__main__":
    unittest.main()

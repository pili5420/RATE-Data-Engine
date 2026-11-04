from __future__ import annotations
import json
import unittest
from unittest.mock import patch

from src.intraday_fugle_github_fence_transport import (
    FugleGitHubFenceTransport,
    FugleGitHubFenceTransportError,
    ref_name_for,
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
    def __init__(self,*args,**kwargs):
        self.closed=False
    def request(self,method,path,body=None,headers=None):
        self.__class__.requests.append((method,path,body,dict(headers or {})))
    def getresponse(self):
        return self.__class__.responses.pop(0)
    def close(self):
        self.closed=True


class TransportTests(unittest.TestCase):
    def setUp(self):
        FakeConnection.responses=[]
        FakeConnection.requests=[]

    def transport(self):
        return FugleGitHubFenceTransport(github_token="synthetic-token")

    @patch("src.intraday_fugle_github_fence_transport.http.client.HTTPSConnection",FakeConnection)
    def test_404_read_is_absent(self):
        FakeConnection.responses=[FakeResponse(404,b"{}")]
        self.assertIsNone(self.transport().read_marker(AUTH))

    @patch("src.intraday_fugle_github_fence_transport.http.client.HTTPSConnection",FakeConnection)
    def test_read_exact_marker(self):
        FakeConnection.responses=[FakeResponse(200,json.dumps({
            "ref":ref_name_for(AUTH),
            "object":{"type":"commit","sha":MAIN},
        }).encode())]
        result=self.transport().read_marker(AUTH)
        self.assertEqual(result["sha"],MAIN)

    @patch("src.intraday_fugle_github_fence_transport.http.client.HTTPSConnection",FakeConnection)
    def test_create_exact_marker(self):
        FakeConnection.responses=[FakeResponse(201,json.dumps({
            "ref":ref_name_for(AUTH),
            "object":{"type":"commit","sha":MAIN},
        }).encode())]
        t=self.transport()
        result=t.create_marker(AUTH,MAIN)
        self.assertEqual(result["sha"],MAIN)
        method,path,body,headers=FakeConnection.requests[0]
        self.assertEqual(method,"POST")
        self.assertEqual(path,"/repos/pili5420/RATE-Data-Engine/git/refs")
        self.assertNotIn("synthetic-token",body.decode())
        self.assertEqual(json.loads(body)["ref"],ref_name_for(AUTH))

    @patch("src.intraday_fugle_github_fence_transport.http.client.HTTPSConnection",FakeConnection)
    def test_redirect_is_forbidden(self):
        FakeConnection.responses=[FakeResponse(302,b"")]
        with self.assertRaisesRegex(FugleGitHubFenceTransportError,"REDIRECT_FORBIDDEN"):
            self.transport().read_marker(AUTH)

    def test_ref_namespace_is_fixed(self):
        self.assertEqual(
            ref_name_for(AUTH),
            "refs/tags/rate-v11-qualification-consumed/fugle-" + "a"*32,
        )


if __name__=="__main__":
    unittest.main()

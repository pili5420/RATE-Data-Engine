"""Tests for bounded Cloudflare HTTPS transport with a fully fake connection."""
from __future__ import annotations

from unittest.mock import patch
import ssl
import unittest

from src.intraday_cloudflare_https_transport import (
    CloudflareHTTPSConnectionTransport,
    CloudflareHTTPSTransportError,
)

ADMIN_URL = "https://api.cloudflare.com/client/v4/accounts/" + "a" * 32 + "/d1/database"
WORKER_URL = "https://rate-v11-qual-123456789abc.synthetic-account.workers.dev/v1/execution-receipts/RATE-001"
ADMIN_HEADERS = {"Authorization": "Bearer synthetic-admin-token", "Content-Type": "application/json"}
WORKER_HEADERS = {"Authorization": "Bearer synthetic-worker-token"}


class FakeResponse:
    def __init__(self, status=200, body=b"{}", content_length=None):
        self.status = status
        self._body = body
        self._content_length = content_length

    def getheader(self, name):
        if name == "Content-Length":
            return self._content_length
        return None

    def read(self, amount=None):
        if amount is None:
            return self._body
        return self._body[:amount]


class FakeConnection:
    instances = []
    response = FakeResponse()
    fail_on = None

    def __init__(self, host, timeout, context):
        self.host = host
        self.timeout = timeout
        self.context = context
        self.closed = False
        self.requests = []
        FakeConnection.instances.append(self)

    def request(self, method, path, body=None, headers=None):
        if FakeConnection.fail_on == "request":
            raise OSError("synthetic-secret-should-not-leak")
        self.requests.append((method, path, body, dict(headers or {})))

    def getresponse(self):
        if FakeConnection.fail_on == "response":
            raise OSError("synthetic-secret-should-not-leak")
        return FakeConnection.response

    def close(self):
        self.closed = True


class TransportTests(unittest.TestCase):
    def setUp(self):
        FakeConnection.instances = []
        FakeConnection.response = FakeResponse()
        FakeConnection.fail_on = None

    def call(self, url=ADMIN_URL, headers=None, scope="ADMIN", method="GET", body=None):
        headers = headers or (ADMIN_HEADERS if scope == "ADMIN" else WORKER_HEADERS)
        transport = CloudflareHTTPSConnectionTransport()
        with patch(
            "src.intraday_cloudflare_https_transport.http.client.HTTPSConnection",
            FakeConnection,
        ):
            result = transport.request(
                method, url, headers, body, credential_scope=scope
            )
        return result, transport

    def test_admin_https_uses_verified_tls_one_connection_and_closes(self):
        result, transport = self.call()
        self.assertEqual(result["status"], 200)
        self.assertEqual(transport.request_count, 1)
        self.assertEqual(result["retry_count"], 0)
        self.assertEqual(result["redirects_followed"], 0)
        conn = FakeConnection.instances[0]
        self.assertEqual(conn.host, "api.cloudflare.com")
        self.assertEqual(conn.timeout, 10)
        self.assertTrue(conn.context.check_hostname)
        self.assertEqual(conn.context.verify_mode, ssl.CERT_REQUIRED)
        self.assertTrue(conn.closed)

    def test_worker_scope_is_limited_to_exact_qualification_workers_dev_host(self):
        result, _ = self.call(url=WORKER_URL, scope="WORKER")
        self.assertEqual(result["host"], "rate-v11-qual-123456789abc.synthetic-account.workers.dev")
        for bad in (
            "https://evil.workers.dev/v1/execution-receipts/RATE-001",
            "https://rate-v11-qual-123456789abc.synthetic-account.workers.dev.attacker.test/x",
            "https://other-123456789abc.synthetic-account.workers.dev/x",
        ):
            with self.subTest(bad=bad), self.assertRaisesRegex(
                CloudflareHTTPSTransportError, "WORKER_HOST_FORBIDDEN"
            ):
                self.call(url=bad, scope="WORKER")

    def test_credential_scope_cannot_cross_hosts(self):
        with self.assertRaisesRegex(CloudflareHTTPSTransportError, "ADMIN_HOST_FORBIDDEN"):
            self.call(url=WORKER_URL, scope="ADMIN", headers=ADMIN_HEADERS)
        with self.assertRaisesRegex(CloudflareHTTPSTransportError, "WORKER_HOST_FORBIDDEN"):
            self.call(url=ADMIN_URL, scope="WORKER", headers=WORKER_HEADERS)
        self.assertEqual(FakeConnection.instances, [])

    def test_non_https_userinfo_query_fragment_port_and_path_escape_fail_preconnect(self):
        bad = (
            "http://api.cloudflare.com/x",
            "https://user@api.cloudflare.com/x",
            "https://api.cloudflare.com:444/x",
            "https://api.cloudflare.com/x?q=1",
            "https://api.cloudflare.com/x#frag",
            "https://api.cloudflare.com/a/../b",
            "https://api.cloudflare.com/a/%2e%2e/b",
        )
        for url in bad:
            with self.subTest(url=url), self.assertRaises(CloudflareHTTPSTransportError):
                self.call(url=url)
        self.assertEqual(FakeConnection.instances, [])

    def test_redirect_is_fail_closed_after_one_request_without_retry(self):
        FakeConnection.response = FakeResponse(status=302, body=b"")
        with self.assertRaisesRegex(CloudflareHTTPSTransportError, "REDIRECT_FORBIDDEN"):
            self.call()
        self.assertEqual(len(FakeConnection.instances), 1)
        self.assertEqual(len(FakeConnection.instances[0].requests), 1)
        self.assertTrue(FakeConnection.instances[0].closed)

    def test_response_size_is_bounded_by_header_and_stream_read(self):
        FakeConnection.response = FakeResponse(
            status=200, body=b"x" * 2048, content_length="2048"
        )
        transport = CloudflareHTTPSConnectionTransport(max_response_bytes=1024)
        with patch(
            "src.intraday_cloudflare_https_transport.http.client.HTTPSConnection",
            FakeConnection,
        ):
            with self.assertRaisesRegex(CloudflareHTTPSTransportError, "RESPONSE_TOO_LARGE"):
                transport.request("GET", ADMIN_URL, ADMIN_HEADERS, credential_scope="ADMIN")
        self.assertTrue(FakeConnection.instances[0].closed)

        self.setUp()
        FakeConnection.response = FakeResponse(status=200, body=b"x" * 1025)
        transport = CloudflareHTTPSConnectionTransport(max_response_bytes=1024)
        with patch(
            "src.intraday_cloudflare_https_transport.http.client.HTTPSConnection",
            FakeConnection,
        ):
            with self.assertRaisesRegex(CloudflareHTTPSTransportError, "RESPONSE_TOO_LARGE"):
                transport.request("GET", ADMIN_URL, ADMIN_HEADERS, credential_scope="ADMIN")
        self.assertTrue(FakeConnection.instances[0].closed)

    def test_transport_exception_is_redacted_closed_and_not_retried(self):
        FakeConnection.fail_on = "response"
        transport = CloudflareHTTPSConnectionTransport()
        with patch(
            "src.intraday_cloudflare_https_transport.http.client.HTTPSConnection",
            FakeConnection,
        ):
            with self.assertRaises(CloudflareHTTPSTransportError) as ctx:
                transport.request("GET", ADMIN_URL, ADMIN_HEADERS, credential_scope="ADMIN")
        message = str(ctx.exception)
        self.assertNotIn("synthetic-admin-token", message)
        self.assertNotIn("synthetic-secret-should-not-leak", message)
        self.assertEqual(transport.request_count, 1)
        self.assertEqual(len(FakeConnection.instances), 1)
        self.assertTrue(FakeConnection.instances[0].closed)

    def test_header_injection_and_missing_bearer_fail_preconnect(self):
        for headers in (
            {"Authorization": "synthetic-admin-token"},
            {"Authorization": "Bearer token\r\nX-Evil: 1"},
            {"Authorization": "Bearer token", "X-Bad\n": "value"},
        ):
            with self.subTest(headers=headers), self.assertRaises(CloudflareHTTPSTransportError):
                self.call(headers=headers)
        self.assertEqual(FakeConnection.instances, [])

    def test_request_body_is_bounded_and_method_allowlisted(self):
        with self.assertRaisesRegex(CloudflareHTTPSTransportError, "REQUEST_TOO_LARGE"):
            self.call(method="POST", body=b"x" * (2 * 1024 * 1024 + 1))
        with self.assertRaisesRegex(CloudflareHTTPSTransportError, "METHOD_FORBIDDEN"):
            self.call(method="PATCH")
        self.assertEqual(FakeConnection.instances, [])


if __name__ == "__main__":
    unittest.main()

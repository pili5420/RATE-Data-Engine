"""Integrate the exact Cloudflare request-shape rehearsal with the bounded HTTPS transport.

The existing 17-request sequence is reused unchanged. Its exact synthetic transport
instance is adapted so every request flows through CloudflareHTTPSConnectionTransport,
while HTTPSConnection is patched to an in-memory fake Cloudflare server.
"""
from __future__ import annotations

import json
from typing import Any, Mapping
from urllib.parse import urlparse
from unittest.mock import patch

from .intraday_cloudflare_d1_http_request_shape_rehearsal import (
    SyntheticCloudflareHTTPTransport,
    rehearse_cloudflare_http_request_shapes,
)
from .intraday_cloudflare_https_transport import (
    ADMIN_HOST,
    CloudflareHTTPSConnectionTransport,
)


class CloudflareHTTPSIntegrationError(RuntimeError):
    pass


def require(condition: bool, reason: str) -> None:
    if not condition:
        raise CloudflareHTTPSIntegrationError(reason)


class _FakeResponse:
    def __init__(self, status: int, payload: Mapping[str, Any]):
        self.status = status
        self._body = json.dumps(payload, separators=(",", ":")).encode("utf-8")

    def getheader(self, name: str):
        if name == "Content-Length":
            return str(len(self._body))
        return None

    def read(self, amount=None):
        if amount is None:
            return self._body
        return self._body[:amount]


def review_cloudflare_https_transport_integration(
    authorization_qualification: Mapping[str, Any],
    scaffold_files: Mapping[str, str],
    *,
    expected_authorization_qualification_sha256: str,
    expected_current_main_sha: str,
) -> dict[str, Any]:
    server = SyntheticCloudflareHTTPTransport()
    bounded = CloudflareHTTPSConnectionTransport()
    original_server_request = SyntheticCloudflareHTTPTransport.request
    connections: list[Any] = []

    class Connection:
        def __init__(self, host, timeout, context):
            self.host = host
            self.timeout = timeout
            self.context = context
            self.closed = False
            self._request = None
            connections.append(self)

        def request(self, method, path, body=None, headers=None):
            self._request = {
                "method": method,
                "path": path,
                "body": body or b"",
                "headers": dict(headers or {}),
            }

        def getresponse(self):
            require(self._request is not None, "CF_HTTPS_INTEGRATION_REQUEST_MISSING")
            status, payload = original_server_request(
                server,
                self._request["method"],
                f"https://{self.host}{self._request['path']}",
                self._request["headers"],
                self._request["body"],
            )
            return _FakeResponse(status, payload)

        def close(self):
            self.closed = True

    def bounded_request(method, url, headers, body=None):
        host = urlparse(url).hostname or ""
        scope = "ADMIN" if host == ADMIN_HOST else "WORKER"
        result = bounded.request(
            method,
            url,
            headers,
            body,
            credential_scope=scope,
        )
        try:
            payload = json.loads(result["body"].decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise CloudflareHTTPSIntegrationError(
                "CF_HTTPS_INTEGRATION_RESPONSE_JSON_INVALID"
            ) from exc
        return result["status"], payload

    # Preserve exact-type guard in the existing request-shape rehearsal while routing
    # every request through the bounded transport.
    server.request = bounded_request  # type: ignore[method-assign]

    with patch(
        "src.intraday_cloudflare_https_transport.http.client.HTTPSConnection",
        Connection,
    ):
        result = rehearse_cloudflare_http_request_shapes(
            authorization_qualification,
            scaffold_files,
            server,
            expected_authorization_qualification_sha256=expected_authorization_qualification_sha256,
            expected_current_main_sha=expected_current_main_sha,
        )

    require(result.get("validation_status") == "PASS",
            "CF_HTTPS_INTEGRATION_SHAPE_REHEARSAL_NOT_PASS")
    require(result.get("request_count") == 17, "CF_HTTPS_INTEGRATION_SHAPE_COUNT_INVALID")
    require(bounded.request_count == 17, "CF_HTTPS_INTEGRATION_BOUNDED_COUNT_INVALID")
    require(len(server.calls) == 17, "CF_HTTPS_INTEGRATION_SERVER_COUNT_INVALID")
    require(len(connections) == 17, "CF_HTTPS_INTEGRATION_CONNECTION_COUNT_INVALID")
    require(all(conn.closed for conn in connections), "CF_HTTPS_INTEGRATION_CONNECTION_NOT_CLOSED")
    require(
        all(conn.context.check_hostname for conn in connections),
        "CF_HTTPS_INTEGRATION_HOSTNAME_VERIFICATION_MISSING",
    )
    require(
        all(conn.timeout == 10 for conn in connections),
        "CF_HTTPS_INTEGRATION_TIMEOUT_DRIFT",
    )

    admin_count = sum(1 for call in server.calls if urlparse(call["url"]).hostname == ADMIN_HOST)
    worker_count = sum(1 for call in server.calls if (urlparse(call["url"]).hostname or "").endswith(".workers.dev"))
    require(admin_count == 11 and worker_count == 6,
            "CF_HTTPS_INTEGRATION_HOST_COUNTS_INVALID")

    return {
        "artifact": "RATE_CLOUDFLARE_D1_HTTPS_TRANSPORT_INTEGRATION_REHEARSAL_V1",
        "validation_status": "PASS",
        "shape_rehearsal_artifact": result["artifact"],
        "bounded_transport": bounded.transport,
        "total_requests": 17,
        "admin_requests": admin_count,
        "worker_requests": worker_count,
        "connections_created": len(connections),
        "connections_closed": sum(1 for conn in connections if conn.closed),
        "tls_hostname_verification_all": True,
        "retry_count": 0,
        "redirects_followed": 0,
        "fallback_used": False,
        "real_network_requests": 0,
        "real_cloudflare_requests": 0,
        "credentials_read": 0,
        "real_resources_created": 0,
        "provider_qualified": False,
        "production_credit": 0,
        "cer081_credit": 0,
        "next_gate": "EXPLICIT_REAL_CLOUDFLARE_QUALIFICATION_EXECUTION",
    }

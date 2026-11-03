"""Bounded HTTPS transport for a future authorized Cloudflare qualification.

The class is production-shaped but this PR's tests patch HTTPSConnection completely.
It has no retry, redirect-follow, fallback, logging or credential persistence.
"""
from __future__ import annotations

import http.client
import re
import ssl
from typing import Any, Mapping
from urllib.parse import urlparse

ADMIN_HOST = "api.cloudflare.com"
WORKER_HOST = re.compile(
    r"^rate-v11-qual-[0-9a-f]{12}\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.workers\.dev$"
)
ALLOWED_METHODS = {"GET", "POST", "PUT", "DELETE"}
MAX_REQUEST_BYTES = 2 * 1024 * 1024
MAX_RESPONSE_BYTES = 1024 * 1024
TIMEOUT_SECONDS = 10


class CloudflareHTTPSTransportError(RuntimeError):
    pass


def require(condition: bool, reason: str) -> None:
    if not condition:
        raise CloudflareHTTPSTransportError(reason)


def _validate_url(url: str, credential_scope: str) -> tuple[str, str]:
    require(isinstance(url, str) and url, "CF_HTTPS_URL_INVALID")
    parsed = urlparse(url)
    require(parsed.scheme == "https", "CF_HTTPS_SCHEME_REQUIRED")
    require(parsed.username is None and parsed.password is None, "CF_HTTPS_USERINFO_FORBIDDEN")
    require(parsed.port in {None, 443}, "CF_HTTPS_CUSTOM_PORT_FORBIDDEN")
    require(not parsed.query and not parsed.fragment, "CF_HTTPS_QUERY_FRAGMENT_FORBIDDEN")
    host = parsed.hostname or ""
    require(host == host.lower(), "CF_HTTPS_HOST_CASE_INVALID")
    if credential_scope == "ADMIN":
        require(host == ADMIN_HOST, "CF_HTTPS_ADMIN_HOST_FORBIDDEN")
    elif credential_scope == "WORKER":
        require(bool(WORKER_HOST.fullmatch(host)), "CF_HTTPS_WORKER_HOST_FORBIDDEN")
    else:
        raise CloudflareHTTPSTransportError("CF_HTTPS_CREDENTIAL_SCOPE_INVALID")

    path = parsed.path or "/"
    require(path.startswith("/"), "CF_HTTPS_PATH_INVALID")
    require(
        ".." not in path
        and "%" not in path
        and "\\" not in path
        and "\r" not in path
        and "\n" not in path,
        "CF_HTTPS_PATH_FORBIDDEN",
    )
    return host, path


def _validate_headers(headers: Mapping[str, str]) -> dict[str, str]:
    require(isinstance(headers, Mapping), "CF_HTTPS_HEADERS_INVALID")
    normalized = {}
    for key, value in headers.items():
        require(
            isinstance(key, str) and isinstance(value, str)
            and key and "\r" not in key and "\n" not in key
            and "\r" not in value and "\n" not in value,
            "CF_HTTPS_HEADER_INJECTION_FORBIDDEN",
        )
        normalized[key] = value
    auth = normalized.get("Authorization")
    require(
        isinstance(auth, str)
        and auth.startswith("Bearer ")
        and len(auth) > len("Bearer "),
        "CF_HTTPS_BEARER_REQUIRED",
    )
    return normalized


class CloudflareHTTPSConnectionTransport:
    """One-connection-per-request HTTPS transport with no retry or redirect following."""

    transport = "CLOUDFLARE_BOUNDED_HTTPS_V1"

    def __init__(
        self,
        *,
        timeout_seconds: int = TIMEOUT_SECONDS,
        max_response_bytes: int = MAX_RESPONSE_BYTES,
    ):
        require(
            isinstance(timeout_seconds, int) and 1 <= timeout_seconds <= TIMEOUT_SECONDS,
            "CF_HTTPS_TIMEOUT_INVALID",
        )
        require(
            isinstance(max_response_bytes, int)
            and 1024 <= max_response_bytes <= MAX_RESPONSE_BYTES,
            "CF_HTTPS_RESPONSE_LIMIT_INVALID",
        )
        self.timeout_seconds = timeout_seconds
        self.max_response_bytes = max_response_bytes
        self.request_count = 0

    def request(
        self,
        method: str,
        url: str,
        headers: Mapping[str, str],
        body: bytes | None = None,
        *,
        credential_scope: str,
    ) -> dict[str, Any]:
        require(method in ALLOWED_METHODS, "CF_HTTPS_METHOD_FORBIDDEN")
        host, path = _validate_url(url, credential_scope)
        safe_headers = _validate_headers(headers)
        payload = body or b""
        require(isinstance(payload, bytes), "CF_HTTPS_BODY_MUST_BE_BYTES")
        require(len(payload) <= MAX_REQUEST_BYTES, "CF_HTTPS_REQUEST_TOO_LARGE")

        context = ssl.create_default_context()
        require(context.check_hostname is True, "CF_HTTPS_HOSTNAME_VERIFICATION_REQUIRED")
        require(context.verify_mode == ssl.CERT_REQUIRED, "CF_HTTPS_CERT_VERIFICATION_REQUIRED")

        conn = http.client.HTTPSConnection(
            host,
            timeout=self.timeout_seconds,
            context=context,
        )
        self.request_count += 1
        try:
            conn.request(method, path, body=payload or None, headers=safe_headers)
            response = conn.getresponse()
            status = int(response.status)
            require(not (300 <= status <= 399), "CF_HTTPS_REDIRECT_FORBIDDEN")

            length_raw = response.getheader("Content-Length")
            if length_raw is not None:
                try:
                    length = int(length_raw)
                except ValueError as exc:
                    raise CloudflareHTTPSTransportError(
                        "CF_HTTPS_CONTENT_LENGTH_INVALID"
                    ) from exc
                require(0 <= length <= self.max_response_bytes,
                        "CF_HTTPS_RESPONSE_TOO_LARGE")

            data = response.read(self.max_response_bytes + 1)
            require(len(data) <= self.max_response_bytes, "CF_HTTPS_RESPONSE_TOO_LARGE")
            return {
                "status": status,
                "body": data,
                "host": host,
                "path": path,
                "credential_scope": credential_scope,
                "request_count": self.request_count,
                "retry_count": 0,
                "redirects_followed": 0,
            }
        except CloudflareHTTPSTransportError:
            raise
        except Exception as exc:
            # Never include headers, body, or credential values in the error.
            raise CloudflareHTTPSTransportError(
                "CF_HTTPS_REQUEST_FAILED:" + type(exc).__name__
            ) from exc
        finally:
            conn.close()

"""Offline request-shape rehearsal for the future real Cloudflare qualification.

The request paths, JSON payloads and Worker multipart metadata match the Cloudflare
API contract, but only an exact synthetic transport is accepted. No network request
can leave this module in engineering review.
"""
from __future__ import annotations

import json
import re
from typing import Any, Mapping
from urllib.parse import urlparse

from .intraday_activation_candidate_review import canonical_digest
from .intraday_cloudflare_d1_deployment_scaffold import (
    EXPECTED_FILES,
    validate_cloudflare_d1_scaffold,
)
from .intraday_cloudflare_d1_real_qualification_authorization import (
    EXPECTED_ADMIN_BUDGET,
    EXPECTED_CLEANUP_BUDGET,
    EXPECTED_RESOURCE_BUDGET,
    EXPECTED_RUNTIME_BUDGET,
)

API_BASE = "https://api.cloudflare.com/client/v4"
ACCOUNT_ID = "a" * 32
D1_ID = "11111111-1111-1111-1111-111111111111"
ACCOUNT_SUBDOMAIN = "synthetic-account"
ADMIN_TOKEN = "synthetic-admin-token"
WORKER_TOKEN = "synthetic-worker-token"
RECEIPT_ID = "RATE-CF-HTTP-001"


class CloudflareHTTPRequestShapeError(RuntimeError):
    pass


def require(condition: bool, reason: str) -> None:
    if not condition:
        raise CloudflareHTTPRequestShapeError(reason)


def _json_body(value: Mapping[str, Any]) -> bytes:
    return json.dumps(value, separators=(",", ":"), sort_keys=True).encode("utf-8")


def _multipart_worker(worker_source: str, database_id: str) -> tuple[str, bytes]:
    boundary = "RATEV11CLOUDFLAREBOUNDARY"
    metadata = {
        "main_module": "worker.mjs",
        "compatibility_date": "2026-11-03",
        "bindings": [{"type": "d1", "name": "DB", "database_id": database_id}],
    }
    parts = [
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="metadata"\r\n'
        "Content-Type: application/json\r\n\r\n"
        + json.dumps(metadata, separators=(",", ":"), sort_keys=True)
        + "\r\n",
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="worker.mjs"; filename="worker.mjs"\r\n'
        "Content-Type: application/javascript+module\r\n\r\n"
        + worker_source
        + "\r\n",
        f"--{boundary}--\r\n",
    ]
    return f"multipart/form-data; boundary={boundary}", "".join(parts).encode("utf-8")


class SyntheticCloudflareHTTPTransport:
    transport = "SYNTHETIC_CLOUDFLARE_HTTP_ONLY"

    def __init__(self):
        self.calls: list[dict[str, Any]] = []
        self.consumed: set[str] = set()
        self.d1_exists = False
        self.worker_exists = False
        self.secret_exists = False
        self.schema_applied = False
        self.receipts: dict[str, dict[str, Any]] = {}

    def consume(self, token: str) -> None:
        require(token not in self.consumed, "CF_HTTP_SINGLE_USE_ALREADY_CONSUMED")
        self.consumed.add(token)

    def request(self, method: str, url: str, headers: Mapping[str, str], body: bytes | None = None):
        call = {
            "method": method,
            "url": url,
            "headers": dict(headers),
            "body": body or b"",
        }
        self.calls.append(call)
        parsed = urlparse(url)

        if parsed.netloc == "api.cloudflare.com":
            require(
                headers.get("Authorization") == "Bearer " + ADMIN_TOKEN,
                "CF_HTTP_ADMIN_AUTH_INVALID",
            )
            require(WORKER_TOKEN not in headers.values(), "CF_HTTP_WORKER_SECRET_LEAK_TO_ADMIN_HEADER")
            prefix = f"/client/v4/accounts/{ACCOUNT_ID}"

            if method == "POST" and parsed.path == prefix + "/d1/database":
                payload = json.loads((body or b"{}").decode())
                require(payload.get("read_replication") == {"mode": "disabled"},
                        "CF_HTTP_D1_REPLICATION_BODY_INVALID")
                require(str(payload.get("name", "")).startswith("rate-v11-qual-"),
                        "CF_HTTP_D1_NAME_INVALID")
                self.d1_exists = True
                return 200, {"success": True, "result": {"uuid": D1_ID, "name": payload["name"], "read_replication": {"mode": "disabled"}}}

            script_match = re.fullmatch(prefix + r"/workers/scripts/([^/]+)", parsed.path)
            if method == "PUT" and script_match:
                text = (body or b"").decode("utf-8")
                require('"main_module":"worker.mjs"' in text, "CF_HTTP_WORKER_MULTIPART_MAIN_MISSING")
                require('"type":"d1"' in text and '"name":"DB"' in text, "CF_HTTP_WORKER_D1_BINDING_MISSING")
                require(f'"database_id":"{D1_ID}"' in text, "CF_HTTP_WORKER_D1_ID_MISMATCH")
                require(WORKER_TOKEN not in text, "CF_HTTP_WORKER_SECRET_EMBEDDED_IN_SCRIPT_UPLOAD")
                self.worker_exists = True
                return 200, {"success": True, "result": {"id": script_match.group(1)}}

            secret_match = re.fullmatch(prefix + r"/workers/scripts/([^/]+)/secrets", parsed.path)
            if method == "PUT" and secret_match:
                payload = json.loads((body or b"{}").decode())
                require(payload == {
                    "name": "RATE_D1_RECEIPT_WORKER_TOKEN",
                    "text": WORKER_TOKEN,
                    "type": "secret_text",
                }, "CF_HTTP_WORKER_SECRET_BODY_INVALID")
                self.secret_exists = True
                return 200, {"success": True, "result": {"name": payload["name"], "type": payload["type"]}}

            query_path = prefix + f"/d1/database/{D1_ID}/query"
            if method == "POST" and parsed.path == query_path:
                payload = json.loads((body or b"{}").decode())
                require(isinstance(payload.get("sql"), str) and "rate_execution_receipts" in payload["sql"],
                        "CF_HTTP_SCHEMA_QUERY_BODY_INVALID")
                self.schema_applied = True
                return 200, {"success": True, "result": [{"success": True}]}

            if method == "GET" and parsed.path == prefix + f"/d1/database/{D1_ID}":
                return 200, {"success": True, "result": {"uuid": D1_ID, "read_replication": {"mode": "disabled"}}}

            if method == "GET" and script_match:
                require(self.worker_exists, "CF_HTTP_WORKER_GET_BEFORE_CREATE")
                return 200, {"raw_worker": True}

            secret_get = re.fullmatch(prefix + r"/workers/scripts/([^/]+)/secrets/RATE_D1_RECEIPT_WORKER_TOKEN", parsed.path)
            if method == "GET" and secret_get:
                return 200, {"success": True, "result": {"name": "RATE_D1_RECEIPT_WORKER_TOKEN", "type": "secret_text"}}

            if method == "GET" and parsed.path == prefix + "/workers/subdomain":
                return 200, {"success": True, "result": {"subdomain": ACCOUNT_SUBDOMAIN}}

            script_subdomain = re.fullmatch(prefix + r"/workers/scripts/([^/]+)/subdomain", parsed.path)
            if method == "GET" and script_subdomain:
                return 200, {"success": True, "result": {"enabled": True, "previews_enabled": False}}

            if method == "DELETE" and script_match:
                self.worker_exists = False
                self.secret_exists = False
                return 200, {"success": True, "result": None}

            if method == "DELETE" and parsed.path == prefix + f"/d1/database/{D1_ID}":
                self.d1_exists = False
                self.schema_applied = False
                return 200, {"success": True, "result": None}

            raise CloudflareHTTPRequestShapeError("CF_HTTP_UNEXPECTED_ADMIN_REQUEST:" + method + ":" + parsed.path)

        if parsed.netloc.endswith(".workers.dev"):
            require(ADMIN_TOKEN not in headers.values(), "CF_HTTP_ADMIN_TOKEN_LEAK_TO_RUNTIME")
            if headers.get("Authorization") != "Bearer " + WORKER_TOKEN:
                return 401, {"error": "UNAUTHORIZED"}
            execution_id = parsed.path.rsplit("/", 1)[-1]
            if method == "GET":
                if execution_id not in self.receipts:
                    return 404, {"error": "NOT_FOUND"}
                return 200, deepcopy_json(self.receipts[execution_id])
            if method == "POST":
                payload = json.loads((body or b"{}").decode())
                if execution_id in self.receipts:
                    return 409, {"error": "ALREADY_EXISTS"}
                self.receipts[execution_id] = {
                    "execution_id": execution_id,
                    "receipt_json": payload["receipt_json"],
                    "receipt_sha256": payload["receipt_sha256"],
                }
                return 201, {"outcome": "CREATED_AND_READBACK_VERIFIED"}
            return 405, {"error": "METHOD_NOT_ALLOWED"}

        raise CloudflareHTTPRequestShapeError("CF_HTTP_UNEXPECTED_HOST:" + parsed.netloc)


def deepcopy_json(value: Mapping[str, Any]) -> dict[str, Any]:
    return json.loads(json.dumps(value))


def _api_headers(content_type: str | None = None) -> dict[str, str]:
    headers = {"Authorization": "Bearer " + ADMIN_TOKEN}
    if content_type:
        headers["Content-Type"] = content_type
    return headers


def rehearse_cloudflare_http_request_shapes(
    authorization_qualification: Mapping[str, Any],
    scaffold_files: Mapping[str, str],
    transport: SyntheticCloudflareHTTPTransport,
    *,
    expected_authorization_qualification_sha256: str,
    expected_current_main_sha: str,
) -> dict[str, Any]:
    require(
        type(transport) is SyntheticCloudflareHTTPTransport
        and transport.transport == "SYNTHETIC_CLOUDFLARE_HTTP_ONLY",
        "CF_HTTP_REAL_TRANSPORT_FORBIDDEN",
    )
    require(
        canonical_digest(authorization_qualification) == expected_authorization_qualification_sha256,
        "CF_HTTP_AUTHORIZATION_HASH_MISMATCH",
    )
    require(
        authorization_qualification.get("artifact")
        == "RATE_CLOUDFLARE_D1_REAL_PROVIDER_QUALIFICATION_AUTHORIZATION_QUALIFICATION_V1"
        and authorization_qualification.get("validation_status") == "PASS"
        and authorization_qualification.get("current_main_sha") == expected_current_main_sha,
        "CF_HTTP_AUTHORIZATION_NOT_PASS",
    )
    require(authorization_qualification.get("admin_operation_budget") == EXPECTED_ADMIN_BUDGET,
            "CF_HTTP_ADMIN_BUDGET_INVALID")
    require(authorization_qualification.get("runtime_probe_budget") == EXPECTED_RUNTIME_BUDGET,
            "CF_HTTP_RUNTIME_BUDGET_INVALID")
    require(authorization_qualification.get("cleanup_operation_budget") == EXPECTED_CLEANUP_BUDGET,
            "CF_HTTP_CLEANUP_BUDGET_INVALID")
    require(authorization_qualification.get("resource_budget") == EXPECTED_RESOURCE_BUDGET,
            "CF_HTTP_RESOURCE_BUDGET_INVALID")
    require(
        authorization_qualification.get("single_use") is True
        and authorization_qualification.get("execution_consumed") is False
        and authorization_qualification.get("automatic_retry_allowed") is False
        and authorization_qualification.get("fallback_allowed") is False,
        "CF_HTTP_SINGLE_USE_BOUNDARY_INVALID",
    )
    static = validate_cloudflare_d1_scaffold(scaffold_files)
    require(static.get("validation_status") == "PASS", "CF_HTTP_SCAFFOLD_NOT_PASS")

    token = expected_authorization_qualification_sha256
    require(token not in transport.consumed, "CF_HTTP_SINGLE_USE_ALREADY_CONSUMED")
    transport.consume(token)

    suffix = token[:12]
    database_name = "rate-v11-qual-" + suffix
    script_name = "rate-v11-qual-" + suffix
    prefix = f"{API_BASE}/accounts/{ACCOUNT_ID}"

    status, created = transport.request(
        "POST", prefix + "/d1/database",
        _api_headers("application/json"),
        _json_body({"name": database_name, "read_replication": {"mode": "disabled"}}),
    )
    require(status == 200 and created["result"]["uuid"] == D1_ID, "CF_HTTP_D1_CREATE_FAILED")

    content_type, multipart = _multipart_worker(scaffold_files[EXPECTED_FILES[0]], D1_ID)
    status, _ = transport.request(
        "PUT", prefix + f"/workers/scripts/{script_name}",
        _api_headers(content_type), multipart,
    )
    require(status == 200, "CF_HTTP_WORKER_UPLOAD_FAILED")

    status, _ = transport.request(
        "PUT", prefix + f"/workers/scripts/{script_name}/secrets",
        _api_headers("application/json"),
        _json_body({"name": "RATE_D1_RECEIPT_WORKER_TOKEN", "text": WORKER_TOKEN, "type": "secret_text"}),
    )
    require(status == 200, "CF_HTTP_SECRET_PUT_FAILED")

    status, _ = transport.request(
        "POST", prefix + f"/d1/database/{D1_ID}/query",
        _api_headers("application/json"),
        _json_body({"sql": scaffold_files[EXPECTED_FILES[1]], "params": []}),
    )
    require(status == 200, "CF_HTTP_SCHEMA_APPLY_FAILED")

    status, meta = transport.request("GET", prefix + f"/d1/database/{D1_ID}", _api_headers())
    require(status == 200 and meta["result"]["read_replication"]["mode"] == "disabled",
            "CF_HTTP_D1_METADATA_INVALID")
    require(transport.request("GET", prefix + f"/workers/scripts/{script_name}", _api_headers())[0] == 200,
            "CF_HTTP_WORKER_READBACK_FAILED")
    secret_meta = transport.request(
        "GET", prefix + f"/workers/scripts/{script_name}/secrets/RATE_D1_RECEIPT_WORKER_TOKEN",
        _api_headers(),
    )
    require(secret_meta[0] == 200 and secret_meta[1]["result"]["name"] == "RATE_D1_RECEIPT_WORKER_TOKEN",
            "CF_HTTP_SECRET_METADATA_INVALID")
    account_subdomain = transport.request("GET", prefix + "/workers/subdomain", _api_headers())
    require(account_subdomain[0] == 200 and account_subdomain[1]["result"]["subdomain"] == ACCOUNT_SUBDOMAIN,
            "CF_HTTP_ACCOUNT_SUBDOMAIN_INVALID")
    script_subdomain = transport.request(
        "GET", prefix + f"/workers/scripts/{script_name}/subdomain", _api_headers()
    )
    require(script_subdomain[0] == 200 and script_subdomain[1]["result"]["enabled"] is True,
            "CF_HTTP_SCRIPT_SUBDOMAIN_DISABLED")

    runtime_base = f"https://{script_name}.{ACCOUNT_SUBDOMAIN}.workers.dev/v1/execution-receipts"
    correct = {"Authorization": "Bearer " + WORKER_TOKEN, "Content-Type": "application/json"}
    require(transport.request("GET", runtime_base + "/" + RECEIPT_ID, {"Authorization": "Bearer wrong"})[0] == 401,
            "CF_HTTP_RUNTIME_UNAUTHORIZED_INVALID")
    require(transport.request("GET", runtime_base + "/RATE-CF-HTTP-MISSING", correct)[0] == 404,
            "CF_HTTP_RUNTIME_MISSING_INVALID")
    receipt_body = {
        "execution_id": RECEIPT_ID,
        "receipt_json": {"state": "CONSUMED_BEFORE_GIT_MUTATION", "source": "synthetic-http"},
        "receipt_sha256": "c" * 64,
    }
    require(transport.request("POST", runtime_base + "/" + RECEIPT_ID, correct, _json_body(receipt_body))[0] == 201,
            "CF_HTTP_RUNTIME_CREATE_INVALID")
    readback = transport.request("GET", runtime_base + "/" + RECEIPT_ID, correct)
    require(readback[0] == 200 and readback[1]["receipt_sha256"] == "c" * 64,
            "CF_HTTP_RUNTIME_READBACK_INVALID")
    require(transport.request("POST", runtime_base + "/" + RECEIPT_ID, correct, _json_body(receipt_body))[0] == 409,
            "CF_HTTP_RUNTIME_DUPLICATE_INVALID")
    require(transport.request("DELETE", runtime_base + "/" + RECEIPT_ID, correct)[0] == 405,
            "CF_HTTP_RUNTIME_METHOD_INVALID")

    require(transport.request("DELETE", prefix + f"/workers/scripts/{script_name}", _api_headers())[0] == 200,
            "CF_HTTP_WORKER_CLEANUP_FAILED")
    require(transport.request("DELETE", prefix + f"/d1/database/{D1_ID}", _api_headers())[0] == 200,
            "CF_HTTP_D1_CLEANUP_FAILED")

    require(len(transport.calls) == 17, "CF_HTTP_REQUEST_COUNT_INVALID")
    require(not transport.worker_exists and not transport.d1_exists, "CF_HTTP_RESIDUAL_RESOURCE")
    return {
        "artifact": "RATE_CLOUDFLARE_D1_HTTP_REQUEST_SHAPE_REHEARSAL_V1",
        "validation_status": "PASS",
        "transport": "SYNTHETIC_CLOUDFLARE_HTTP_ONLY",
        "request_count": 17,
        "admin_and_cleanup_requests": 11,
        "runtime_requests": 6,
        "database_name": database_name,
        "script_name": script_name,
        "workers_dev_host": f"{script_name}.{ACCOUNT_SUBDOMAIN}.workers.dev",
        "d1_id": D1_ID,
        "single_use_consumed": True,
        "retry_count": 0,
        "fallback_used": False,
        "real_network_requests": 0,
        "real_cloudflare_requests": 0,
        "credentials_read": 0,
        "real_resources_created": 0,
        "provider_qualified": False,
        "production_credit": 0,
        "cer081_credit": 0,
        "next_gate": "REAL_CLOUDFLARE_HTTPS_TRANSPORT_ADAPTER_QUALIFICATION",
    }

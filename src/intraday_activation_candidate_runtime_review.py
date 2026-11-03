"""Synthetic semantic review for the in-memory intraday provider runtime candidate.

The review executes only an externally hash-bound candidate runtime with a patched
fake HTTPSConnection. No real network request or real credential is possible.
"""
from __future__ import annotations

import ast
from datetime import datetime, timezone
import hashlib
import http.client
import json
from typing import Any, Mapping
from unittest.mock import patch

from .intraday_activation_candidate_syntax_review import (
    validate_activation_candidate_syntax,
)
from .intraday_phase2_admission import (
    expected_universe_binding,
    qualify_phase2_intraday_feed,
)

ALLOWED_RUNTIME_IMPORTS = {
    "__future__",
    "datetime",
    "http.client",
    "json",
    "math",
}
FORBIDDEN_CALLS = {
    "open",
    "eval",
    "exec",
    "compile",
    "__import__",
    "os.system",
    "os.popen",
    "subprocess.run",
    "subprocess.Popen",
    "socket.socket",
}


class ActivationCandidateRuntimeReviewError(RuntimeError):
    pass


def require(condition: bool, reason: str) -> None:
    if not condition:
        raise ActivationCandidateRuntimeReviewError(reason)


def _call_name(call: ast.Call) -> str:
    func = call.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        parts = [func.attr]
        value = func.value
        while isinstance(value, ast.Attribute):
            parts.append(value.attr)
            value = value.value
        if isinstance(value, ast.Name):
            parts.append(value.id)
        return ".".join(reversed(parts))
    return ""


def _runtime_ast_guard(source: str) -> ast.Module:
    try:
        tree = ast.parse(source, filename="src/intraday_provider_runtime.py")
    except SyntaxError as exc:
        raise ActivationCandidateRuntimeReviewError(
            "RUNTIME_SEMANTIC_PYTHON_INVALID"
        ) from exc

    for node in tree.body:
        if isinstance(node, ast.Expr):
            require(
                isinstance(node.value, ast.Constant)
                and isinstance(node.value.value, str),
                "RUNTIME_SEMANTIC_TOP_LEVEL_EXECUTION_FORBIDDEN",
            )
        elif isinstance(node, ast.Import):
            require(
                all(alias.name in ALLOWED_RUNTIME_IMPORTS for alias in node.names),
                "RUNTIME_SEMANTIC_IMPORT_FORBIDDEN",
            )
        elif isinstance(node, ast.ImportFrom):
            require(
                (node.module or "") in ALLOWED_RUNTIME_IMPORTS,
                "RUNTIME_SEMANTIC_IMPORT_FORBIDDEN",
            )
        elif not isinstance(node, (ast.Assign, ast.FunctionDef)):
            raise ActivationCandidateRuntimeReviewError(
                "RUNTIME_SEMANTIC_TOP_LEVEL_EXECUTION_FORBIDDEN"
            )

    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            require(
                _call_name(node) not in FORBIDDEN_CALLS,
                "RUNTIME_SEMANTIC_FORBIDDEN_CALL",
            )
    return tree


class _FakeResponse:
    def __init__(self, status: int, body: bytes):
        self.status = status
        self._body = body

    def read(self):
        return self._body


class _FakeTransport:
    def __init__(self, *, status: int = 200, malformed_json: bool = False,
                 missing_total: bool = False, now_utc: datetime):
        self.status = status
        self.malformed_json = malformed_json
        self.missing_total = missing_total
        self.now_utc = now_utc
        self.requests: list[dict[str, Any]] = []
        self.connections: list[Any] = []

    def factory(self, host, timeout=10):
        transport = self

        class Connection:
            def __init__(self):
                self.closed = False
                self.path = None
                self.headers = None
                transport.connections.append(self)

            def request(self, method, path, headers=None):
                self.path = path
                self.headers = dict(headers or {})
                transport.requests.append({
                    "host": host,
                    "timeout": timeout,
                    "method": method,
                    "path": path,
                    "headers": dict(headers or {}),
                })

            def getresponse(self):
                if transport.malformed_json:
                    body = b"{"
                else:
                    symbol = (self.path or "").rsplit("/", 1)[-1]
                    payload = {
                        "symbol": symbol,
                        "lastUpdated": transport.now_utc.isoformat(),
                        "lastPrice": 100.0,
                    }
                    if not transport.missing_total:
                        payload["total"] = {
                            "tradeVolume": 1000,
                            "tradeValue": 100000.0,
                        }
                    body = json.dumps(payload).encode("utf-8")
                return _FakeResponse(transport.status, body)

            def close(self):
                self.closed = True

        return Connection()


def _load_runtime(source: str, transport: _FakeTransport) -> dict[str, Any]:
    _runtime_ast_guard(source)
    namespace: dict[str, Any] = {
        "__name__": "rate_candidate_runtime_synthetic",
        "__file__": "<in-memory-candidate-runtime>",
    }
    with patch.object(http.client, "HTTPSConnection", transport.factory):
        exec(compile(source, "<in-memory-candidate-runtime>", "exec"), namespace, namespace)
    return namespace


def _call_runtime(
    source: str,
    transport: _FakeTransport,
    symbols,
    *,
    trading_date: str,
    cadence: str,
    api_key: str,
):
    namespace = _load_runtime(source, transport)
    fn = namespace.get("acquire_intraday_feed")
    require(callable(fn), "RUNTIME_SEMANTIC_ACQUIRE_FUNCTION_MISSING")
    with patch.object(http.client, "HTTPSConnection", transport.factory):
        return fn(
            symbols,
            trading_date=trading_date,
            cadence=cadence,
            api_key=api_key,
        )


def review_candidate_runtime_synthetic(
    candidate_files: Mapping[str, str],
    *,
    expected_runtime_sha256: str,
    expected_provider_name: str,
    expected_secret_name: str,
    trading_date: str,
    cadence: str,
    now_utc: datetime,
) -> dict[str, Any]:
    require(now_utc.tzinfo is not None and now_utc.utcoffset() is not None,
            "RUNTIME_SEMANTIC_NOW_TIMEZONE_REQUIRED")
    validate_activation_candidate_syntax(
        candidate_files,
        expected_provider_name=expected_provider_name,
        expected_secret_name=expected_secret_name,
    )
    source = candidate_files["src/intraday_provider_runtime.py"]
    actual_hash = hashlib.sha256(source.encode("utf-8")).hexdigest()
    require(actual_hash == expected_runtime_sha256,
            "RUNTIME_SEMANTIC_RUNTIME_HASH_MISMATCH")
    _runtime_ast_guard(source)

    trusted, _ = expected_universe_binding()
    symbols = list(trusted.items())
    synthetic_key = "synthetic-key-not-a-real-secret"

    success_transport = _FakeTransport(now_utc=now_utc)
    result = _call_runtime(
        source,
        success_transport,
        symbols,
        trading_date=trading_date,
        cadence=cadence,
        api_key=synthetic_key,
    )
    require(result.get("requests") == 30, "RUNTIME_SEMANTIC_REQUEST_COUNT_INVALID")
    require(result.get("automatic_retries") == 0, "RUNTIME_SEMANTIC_RETRY_INVALID")
    require(result.get("fallback_used") is False, "RUNTIME_SEMANTIC_FALLBACK_INVALID")
    records = result.get("records")
    require(isinstance(records, list) and len(records) == 30,
            "RUNTIME_SEMANTIC_RECORD_COUNT_INVALID")
    require(len(success_transport.requests) == 30,
            "RUNTIME_SEMANTIC_TRANSPORT_REQUEST_COUNT_INVALID")
    require(
        all(item["host"] == "api.fugle.tw"
            and item["method"] == "GET"
            and item["headers"].get("X-API-KEY") == synthetic_key
            for item in success_transport.requests),
        "RUNTIME_SEMANTIC_TRANSPORT_BINDING_INVALID",
    )
    require(
        len(success_transport.connections) == 30
        and all(conn.closed for conn in success_transport.connections),
        "RUNTIME_SEMANTIC_CONNECTION_NOT_CLOSED",
    )

    feed = {
        "artifact": "RATE_AUTHORIZED_TAIWAN_INTRADAY_FEED_V1",
        "authorization_status": "PASS",
        "validation_status": "PASS",
        "source_status": "PASS",
        "freshness_status": "PASS",
        "blocked_dependencies": [],
        "source_authority": "AUTHORIZED_TAIWAN_INTRADAY_FEED",
        "provider_authority": "SYNTHETIC_ACCEPTED_PROVIDER_AUTHORITY",
        "license_scope": {
            "automated_production_use": True,
            "markets": ["TWSE", "TPEX"],
        },
        "trading_date": trading_date,
        "cadence": cadence,
        "fallback_used": False,
        "records": records,
    }
    qualified = qualify_phase2_intraday_feed(
        feed,
        trading_date=trading_date,
        cadence=cadence,
        now_utc=now_utc,
    )
    require(qualified.get("validation_status") == "PASS"
            and qualified.get("coverage") == "30/30"
            and qualified.get("selected_market_counts") == {"TWSE": 25, "TPEX": 5},
            "RUNTIME_SEMANTIC_AUTHORITATIVE_QUALIFICATION_FAILED")

    for bad_symbols in (symbols[:-1], symbols + [("9999", "TWSE")]):
        transport = _FakeTransport(now_utc=now_utc)
        try:
            _call_runtime(
                source, transport, bad_symbols,
                trading_date=trading_date, cadence=cadence, api_key=synthetic_key,
            )
        except RuntimeError as exc:
            require("EXACT_30_REQUIRED" in str(exc),
                    "RUNTIME_SEMANTIC_COUNT_FAIL_REASON_INVALID")
        else:
            raise ActivationCandidateRuntimeReviewError(
                "RUNTIME_SEMANTIC_COUNT_FAIL_CLOSED_MISSING"
            )
        require(len(transport.requests) == 0,
                "RUNTIME_SEMANTIC_COUNT_FAILURE_NETWORK_ATTEMPT")

    empty_key_transport = _FakeTransport(now_utc=now_utc)
    try:
        _call_runtime(
            source, empty_key_transport, symbols,
            trading_date=trading_date, cadence=cadence, api_key="",
        )
    except RuntimeError as exc:
        require("API_KEY_MISSING" in str(exc),
                "RUNTIME_SEMANTIC_EMPTY_KEY_FAIL_REASON_INVALID")
    else:
        raise ActivationCandidateRuntimeReviewError(
            "RUNTIME_SEMANTIC_EMPTY_KEY_FAIL_CLOSED_MISSING"
        )
    require(len(empty_key_transport.requests) == 0,
            "RUNTIME_SEMANTIC_EMPTY_KEY_NETWORK_ATTEMPT")

    failure_evidence = {}
    for status in (302, 403, 429):
        transport = _FakeTransport(status=status, now_utc=now_utc)
        try:
            _call_runtime(
                source, transport, symbols,
                trading_date=trading_date, cadence=cadence, api_key=synthetic_key,
            )
        except RuntimeError as exc:
            require(f"HTTP_{status}" in str(exc),
                    f"RUNTIME_SEMANTIC_HTTP_{status}_FAIL_REASON_INVALID")
        else:
            raise ActivationCandidateRuntimeReviewError(
                f"RUNTIME_SEMANTIC_HTTP_{status}_FAIL_CLOSED_MISSING"
            )
        require(len(transport.requests) == 1,
                f"RUNTIME_SEMANTIC_HTTP_{status}_REQUEST_COUNT_INVALID")
        require(len(transport.connections) == 1 and transport.connections[0].closed,
                f"RUNTIME_SEMANTIC_HTTP_{status}_CONNECTION_NOT_CLOSED")
        failure_evidence[str(status)] = {
            "requests": 1,
            "retries": 0,
            "connection_closed": True,
        }

    malformed = _FakeTransport(malformed_json=True, now_utc=now_utc)
    try:
        _call_runtime(
            source, malformed, symbols,
            trading_date=trading_date, cadence=cadence, api_key=synthetic_key,
        )
    except json.JSONDecodeError:
        pass
    else:
        raise ActivationCandidateRuntimeReviewError(
            "RUNTIME_SEMANTIC_MALFORMED_JSON_FAIL_CLOSED_MISSING"
        )
    require(len(malformed.requests) == 1,
            "RUNTIME_SEMANTIC_MALFORMED_JSON_REQUEST_COUNT_INVALID")
    require(malformed.connections[0].closed,
            "RUNTIME_SEMANTIC_MALFORMED_JSON_CONNECTION_NOT_CLOSED")

    missing_total = _FakeTransport(missing_total=True, now_utc=now_utc)
    try:
        _call_runtime(
            source, missing_total, symbols,
            trading_date=trading_date, cadence=cadence, api_key=synthetic_key,
        )
    except RuntimeError as exc:
        require("TOTAL_MISSING" in str(exc),
                "RUNTIME_SEMANTIC_TOTAL_FAIL_REASON_INVALID")
    else:
        raise ActivationCandidateRuntimeReviewError(
            "RUNTIME_SEMANTIC_TOTAL_FAIL_CLOSED_MISSING"
        )
    require(len(missing_total.requests) == 1 and missing_total.connections[0].closed,
            "RUNTIME_SEMANTIC_TOTAL_FAILURE_TRANSPORT_INVALID")

    return {
        "artifact": "RATE_INTRADAY_ACTIVATION_CANDIDATE_RUNTIME_SEMANTIC_REVIEW_V1",
        "validation_status": "PASS",
        "transport": "SYNTHETIC_FAKE_HTTPS_ONLY",
        "real_network_requests": 0,
        "synthetic_success_requests": 30,
        "coverage": qualified["coverage"],
        "market_counts": qualified["selected_market_counts"],
        "runtime_sha256": actual_hash,
        "connections_closed": 30,
        "automatic_retries": 0,
        "fallback_used": False,
        "http_fail_closed": failure_evidence,
        "empty_key_requests": 0,
        "count_mismatch_requests": 0,
        "malformed_json_requests": 1,
        "provider_accepted": False,
        "apply_allowed": False,
        "activation_execution_allowed": False,
        "external_dependency_resolved": False,
        "registry_activation_allowed": False,
        "repository_writes": 0,
        "production_credit": 0,
        "cer081_credit": 0,
    }

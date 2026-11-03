"""Local semantic review for the Cloudflare Worker + D1 receipt-store scaffold.

This review executes the generated schema in SQLite and models the Worker/client
protocol locally. It performs no Cloudflare request and reads no real credential.
"""
from __future__ import annotations

from copy import deepcopy
import json
import re
import sqlite3
from typing import Any, Mapping

from .intraday_cloudflare_d1_deployment_scaffold import (
    EXPECTED_FILES,
    validate_cloudflare_d1_scaffold,
)

ROUTE = re.compile(r"^/v1/execution-receipts/([A-Za-z0-9._-]{1,128})$")


class D1LocalSemanticError(RuntimeError):
    pass


def require(condition: bool, reason: str) -> None:
    if not condition:
        raise D1LocalSemanticError(reason)


def valid_execution_id(value: str) -> bool:
    return bool(value) and ".." not in value and not value.endswith(".") and not value.lower().endswith(".lock")


class LocalWorkerD1Model:
    """Offline semantic model backed by SQLite in-memory state."""

    def __init__(self, schema_sql: str, *, token: str = "synthetic-token"):
        self.db = sqlite3.connect(":memory:")
        self.db.row_factory = sqlite3.Row
        self.db.executescript(schema_sql)
        self.token = token
        self.post_calls = 0
        self.get_calls = 0
        self.insert_attempts = 0

    def close(self):
        self.db.close()

    def _read(self, execution_id: str):
        row = self.db.execute(
            "SELECT execution_id, receipt_json, receipt_sha256 FROM rate_execution_receipts WHERE execution_id = ? LIMIT 1",
            (execution_id,),
        ).fetchone()
        return dict(row) if row is not None else None

    def request(self, method: str, path: str, authorization: str | None, body: Mapping[str, Any] | None = None,
                *, fail_before_insert: bool = False):
        if authorization != "Bearer " + self.token:
            return 401, {"error": "UNAUTHORIZED"}
        match = ROUTE.fullmatch(path)
        if not match or not valid_execution_id(match.group(1)):
            return 404, {"error": "NOT_FOUND"}
        execution_id = match.group(1)

        if method == "GET":
            self.get_calls += 1
            row = self._read(execution_id)
            if row is None:
                return 404, {"error": "NOT_FOUND"}
            return 200, {
                "execution_id": row["execution_id"],
                "receipt_json": json.loads(row["receipt_json"]),
                "receipt_sha256": row["receipt_sha256"],
            }

        if method != "POST":
            return 405, {"error": "METHOD_NOT_ALLOWED"}

        self.post_calls += 1
        if (
            not isinstance(body, Mapping)
            or body.get("execution_id") != execution_id
            or not isinstance(body.get("receipt_json"), Mapping)
            or not isinstance(body.get("receipt_sha256"), str)
            or re.fullmatch(r"[0-9a-f]{64}", body["receipt_sha256"]) is None
        ):
            return 400, {"error": "INVALID_RECEIPT"}

        receipt_text = json.dumps(body["receipt_json"], separators=(",", ":"), ensure_ascii=False)
        self.insert_attempts += 1
        if fail_before_insert:
            return 503, {"error": "D1_CREATE_FAILED"}
        try:
            self.db.execute(
                "INSERT INTO rate_execution_receipts (execution_id, receipt_json, receipt_sha256, created_at) VALUES (?, ?, ?, ?)",
                (execution_id, receipt_text, body["receipt_sha256"], "2026-11-04T01:35:00Z"),
            )
            self.db.commit()
        except sqlite3.IntegrityError:
            return 409, {"error": "ALREADY_EXISTS"}

        row = self._read(execution_id)
        if row is None or row["receipt_sha256"] != body["receipt_sha256"] or row["receipt_json"] != receipt_text:
            return 503, {"error": "READBACK_MISMATCH"}
        return 201, {"outcome": "CREATED_AND_READBACK_VERIFIED"}

    def raw_update(self, execution_id: str, replacement: str):
        self.db.execute(
            "UPDATE rate_execution_receipts SET receipt_json = ? WHERE execution_id = ?",
            (replacement, execution_id),
        )
        self.db.commit()

    def raw_delete(self, execution_id: str):
        self.db.execute(
            "DELETE FROM rate_execution_receipts WHERE execution_id = ?",
            (execution_id,),
        )
        self.db.commit()


def client_post_with_ambiguous_transport_readback(
    worker: LocalWorkerD1Model,
    *,
    execution_id: str,
    body: Mapping[str, Any],
    token: str = "synthetic-token",
) -> dict[str, Any]:
    status, payload = worker.request(
        "POST",
        "/v1/execution-receipts/" + execution_id,
        "Bearer " + token,
        body,
    )
    # Model: server completed POST but its HTTP response was lost to the caller.
    require(status == 201, "D1_LOCAL_AMBIGUOUS_PRECONDITION_FAILED")
    status2, payload2 = worker.request(
        "GET",
        "/v1/execution-receipts/" + execution_id,
        "Bearer " + token,
    )
    require(status2 == 200, "D1_LOCAL_AMBIGUOUS_READBACK_FAILED")
    require(
        payload2.get("receipt_sha256") == body["receipt_sha256"]
        and payload2.get("receipt_json") == body["receipt_json"],
        "D1_LOCAL_AMBIGUOUS_READBACK_CONFLICT",
    )
    require(worker.post_calls == 1 and worker.insert_attempts == 1,
            "D1_LOCAL_AMBIGUOUS_POST_RETRY_DETECTED")
    return {
        "outcome": "AMBIGUOUS_HTTP_CONFIRMED_BY_GET",
        "post_calls": worker.post_calls,
        "get_calls": worker.get_calls,
        "insert_attempts": worker.insert_attempts,
        "post_retries": 0,
    }


def review_cloudflare_d1_local_semantics(files: Mapping[str, str]) -> dict[str, Any]:
    static = validate_cloudflare_d1_scaffold(files)
    require(static.get("validation_status") == "PASS", "D1_LOCAL_STATIC_REVIEW_NOT_PASS")
    schema = files[EXPECTED_FILES[1]]
    worker = LocalWorkerD1Model(schema)
    try:
        body = {
            "execution_id": "RATE-EXEC-LOCAL-001",
            "receipt_json": {"state": "CONSUMED_BEFORE_GIT_MUTATION", "value": 1},
            "receipt_sha256": "a" * 64,
        }
        status, _ = worker.request(
            "POST", "/v1/execution-receipts/RATE-EXEC-LOCAL-001",
            "Bearer synthetic-token", body,
        )
        require(status == 201, "D1_LOCAL_CREATE_FAILED")

        duplicate_status, _ = worker.request(
            "POST", "/v1/execution-receipts/RATE-EXEC-LOCAL-001",
            "Bearer synthetic-token", body,
        )
        require(duplicate_status == 409, "D1_LOCAL_DUPLICATE_NOT_FAIL_CLOSED")

        get_status, get_body = worker.request(
            "GET", "/v1/execution-receipts/RATE-EXEC-LOCAL-001",
            "Bearer synthetic-token",
        )
        require(get_status == 200 and get_body["receipt_sha256"] == "a" * 64,
                "D1_LOCAL_READBACK_FAILED")

        try:
            worker.raw_update("RATE-EXEC-LOCAL-001", "{}")
        except sqlite3.DatabaseError as exc:
            require("IMMUTABLE_RECEIPT" in str(exc), "D1_LOCAL_UPDATE_GUARD_WRONG_ERROR")
        else:
            raise D1LocalSemanticError("D1_LOCAL_UPDATE_GUARD_MISSING")

        try:
            worker.raw_delete("RATE-EXEC-LOCAL-001")
        except sqlite3.DatabaseError as exc:
            require("IMMUTABLE_RECEIPT" in str(exc), "D1_LOCAL_DELETE_GUARD_WRONG_ERROR")
        else:
            raise D1LocalSemanticError("D1_LOCAL_DELETE_GUARD_MISSING")
    finally:
        worker.close()

    ambiguous_worker = LocalWorkerD1Model(schema)
    try:
        body2 = {
            "execution_id": "RATE-EXEC-LOCAL-AMBIG",
            "receipt_json": {"state": "CONSUMED_BEFORE_GIT_MUTATION", "value": 2},
            "receipt_sha256": "b" * 64,
        }
        ambiguous = client_post_with_ambiguous_transport_readback(
            ambiguous_worker,
            execution_id="RATE-EXEC-LOCAL-AMBIG",
            body=body2,
        )
    finally:
        ambiguous_worker.close()

    return {
        "artifact": "RATE_INTRADAY_CLOUDFLARE_D1_LOCAL_SEMANTIC_REVIEW_V1",
        "validation_status": "PASS",
        "schema_execution": "SQLITE_IN_MEMORY",
        "duplicate_primary_key_status": 409,
        "update_guard": "PASS",
        "delete_guard": "PASS",
        "ambiguous_http_outcome": ambiguous,
        "real_cloudflare_requests": 0,
        "credentials_read": 0,
        "resources_created": 0,
        "deployment_ready": False,
        "provider_qualified": False,
        "production_credit": 0,
        "cer081_credit": 0,
        "next_gate": "CLOUDFLARE_D1_SCAFFOLD_NODE_WORKER_REVIEW",
    }

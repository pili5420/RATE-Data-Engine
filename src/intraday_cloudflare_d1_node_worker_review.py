"""Execute the generated Cloudflare Worker source in Node with a fake D1 binding.

The review is fully local. It imports the actual worker.mjs source, supplies a fake
D1 binding, and performs no outbound network or Cloudflare operation.
"""
from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import tempfile
from typing import Any, Mapping

from .intraday_cloudflare_d1_deployment_scaffold import (
    EXPECTED_FILES,
    validate_cloudflare_d1_scaffold,
)


class D1NodeWorkerReviewError(RuntimeError):
    pass


def require(condition: bool, reason: str) -> None:
    if not condition:
        raise D1NodeWorkerReviewError(reason)


HARNESS = r'''
import worker from "./worker.mjs";

class FakeStatement {
  constructor(db, sql) {
    this.db = db;
    this.sql = sql;
    this.args = [];
  }
  bind(...args) {
    this.args = args;
    return this;
  }
  async first() {
    if (!this.sql.startsWith("SELECT ")) throw new Error("UNEXPECTED_FIRST_SQL");
    const executionId = this.args[0];
    const value = this.db.records.get(executionId);
    return value ? { ...value } : null;
  }
  async run() {
    if (!this.sql.startsWith("INSERT INTO rate_execution_receipts")) {
      throw new Error("UNEXPECTED_RUN_SQL");
    }
    this.db.insertAttempts += 1;
    if (this.db.failBeforeInsert) {
      throw new Error("D1 unavailable");
    }
    const [executionId, receiptJson, receiptSha256] = this.args;
    if (this.db.records.has(executionId)) {
      throw new Error("UNIQUE constraint failed: rate_execution_receipts.execution_id");
    }
    this.db.records.set(executionId, {
      execution_id: executionId,
      receipt_json: receiptJson,
      receipt_sha256: receiptSha256,
    });
    return { success: true };
  }
}

class FakeDB {
  constructor() {
    this.records = new Map();
    this.insertAttempts = 0;
    this.failBeforeInsert = false;
  }
  prepare(sql) {
    return new FakeStatement(this, sql);
  }
}

const env = {
  DB: new FakeDB(),
  RATE_D1_RECEIPT_WORKER_TOKEN: "synthetic-token",
};

async function call(method, path, token, body = undefined) {
  const init = {
    method,
    headers: { authorization: token },
  };
  if (body !== undefined) {
    init.headers["content-type"] = "application/json";
    init.body = JSON.stringify(body);
  }
  const request = new Request("https://local.invalid" + path, init);
  const response = await worker.fetch(request, env);
  let payload = null;
  try {
    payload = await response.json();
  } catch {
    payload = null;
  }
  return { status: response.status, payload };
}

const path = "/v1/execution-receipts/RATE-NODE-001";
const body = {
  execution_id: "RATE-NODE-001",
  receipt_json: { state: "CONSUMED_BEFORE_GIT_MUTATION", value: 1 },
  receipt_sha256: "a".repeat(64),
};

const unauthorized = await call("GET", path, "Bearer wrong");
const badRoute = await call("GET", "/v1/execution-receipts/BAD..ID", "Bearer synthetic-token");
const badMethod = await call("DELETE", path, "Bearer synthetic-token");
const created = await call("POST", path, "Bearer synthetic-token", body);
const readback = await call("GET", path, "Bearer synthetic-token");
const duplicate = await call("POST", path, "Bearer synthetic-token", body);

env.DB.failBeforeInsert = true;
const failed = await call(
  "POST",
  "/v1/execution-receipts/RATE-NODE-FAIL",
  "Bearer synthetic-token",
  {
    execution_id: "RATE-NODE-FAIL",
    receipt_json: { state: "CONSUMED_BEFORE_GIT_MUTATION", value: 2 },
    receipt_sha256: "b".repeat(64),
  },
);
const failedRead = await call(
  "GET",
  "/v1/execution-receipts/RATE-NODE-FAIL",
  "Bearer synthetic-token",
);

console.log(JSON.stringify({
  unauthorized,
  badRoute,
  badMethod,
  created,
  readback,
  duplicate,
  failed,
  failedRead,
  insertAttempts: env.DB.insertAttempts,
  recordCount: env.DB.records.size,
}));
'''


def review_cloudflare_d1_node_worker(files: Mapping[str, str]) -> dict[str, Any]:
    static = validate_cloudflare_d1_scaffold(files)
    require(static.get("validation_status") == "PASS", "D1_NODE_STATIC_REVIEW_NOT_PASS")
    node = shutil.which("node")
    require(node is not None, "D1_NODE_RUNTIME_MISSING")

    with tempfile.TemporaryDirectory(prefix="rate-d1-node-review-") as tmp:
        root = Path(tmp)
        (root / "worker.mjs").write_text(files[EXPECTED_FILES[0]], encoding="utf-8", newline="")
        (root / "harness.mjs").write_text(HARNESS, encoding="utf-8", newline="")
        completed = subprocess.run(
            [node, str(root / "harness.mjs")],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
    require(completed.returncode == 0, "D1_NODE_WORKER_EXECUTION_FAILED:" + completed.stderr[-1000:])
    lines = [line for line in completed.stdout.splitlines() if line.strip()]
    require(lines, "D1_NODE_WORKER_OUTPUT_MISSING")
    try:
        result = json.loads(lines[-1])
    except json.JSONDecodeError as exc:
        raise D1NodeWorkerReviewError("D1_NODE_WORKER_OUTPUT_INVALID") from exc

    require(result["unauthorized"]["status"] == 401, "D1_NODE_AUTH_FAIL_CLOSED_INVALID")
    require(result["badRoute"]["status"] == 404, "D1_NODE_ROUTE_FAIL_CLOSED_INVALID")
    require(result["badMethod"]["status"] == 405, "D1_NODE_METHOD_FAIL_CLOSED_INVALID")
    require(
        result["created"]["status"] == 201
        and result["created"]["payload"]["outcome"] == "CREATED_AND_READBACK_VERIFIED",
        "D1_NODE_CREATE_INVALID",
    )
    require(
        result["readback"]["status"] == 200
        and result["readback"]["payload"]["receipt_sha256"] == "a" * 64
        and result["readback"]["payload"]["receipt_json"]["value"] == 1,
        "D1_NODE_READBACK_INVALID",
    )
    require(
        result["duplicate"]["status"] == 409
        and result["duplicate"]["payload"]["error"] == "ALREADY_EXISTS",
        "D1_NODE_DUPLICATE_NOT_FAIL_CLOSED",
    )
    require(
        result["failed"]["status"] == 503
        and result["failed"]["payload"]["error"] == "D1_CREATE_FAILED"
        and result["failedRead"]["status"] == 404,
        "D1_NODE_DATABASE_FAILURE_INVALID",
    )
    require(result["insertAttempts"] == 3, "D1_NODE_INSERT_RETRY_DETECTED")
    require(result["recordCount"] == 1, "D1_NODE_UNEXPECTED_RECORD_COUNT")

    return {
        "artifact": "RATE_INTRADAY_CLOUDFLARE_D1_NODE_WORKER_REVIEW_V1",
        "validation_status": "PASS",
        "runtime": "NODE_EXECUTED_ACTUAL_WORKER_MJS",
        "unauthorized_status": 401,
        "bad_route_status": 404,
        "bad_method_status": 405,
        "create_status": 201,
        "read_status": 200,
        "duplicate_status": 409,
        "database_failure_status": 503,
        "insert_attempts": 3,
        "insert_retries": 0,
        "outbound_network_requests": 0,
        "real_cloudflare_requests": 0,
        "credentials_read": 0,
        "resources_created": 0,
        "provider_qualified": False,
        "production_credit": 0,
        "cer081_credit": 0,
        "next_gate": "CLOUDFLARE_D1_REAL_PROVIDER_QUALIFICATION",
    }

"""Build and statically review a Cloudflare Worker + D1 deployment scaffold.

The scaffold is non-deploying: database identifiers remain placeholders and no
Cloudflare request or credential access occurs.
"""
from __future__ import annotations

import json
from typing import Any, Mapping

from .intraday_activation_candidate_review import canonical_digest

EXPECTED_FILES = (
    "cloudflare/rate-execution-receipts/worker.mjs",
    "cloudflare/rate-execution-receipts/schema.sql",
    "cloudflare/rate-execution-receipts/wrangler.jsonc",
)
PLACEHOLDER_DB_ID = "00000000-0000-0000-0000-000000000000"
PLACEHOLDER_DB_NAME = "RATE_RECEIPT_DB_REQUIRES_SEPARATE_QUALIFICATION"


class D1ScaffoldError(RuntimeError):
    pass


def require(condition: bool, reason: str) -> None:
    if not condition:
        raise D1ScaffoldError(reason)


def build_cloudflare_d1_scaffold(
    candidate_qualification: Mapping[str, Any],
    *,
    expected_candidate_qualification_sha256: str,
) -> dict[str, Any]:
    require(isinstance(candidate_qualification, Mapping), "D1_SCAFFOLD_CANDIDATE_INVALID")
    require(
        canonical_digest(candidate_qualification) == expected_candidate_qualification_sha256,
        "D1_SCAFFOLD_CANDIDATE_HASH_MISMATCH",
    )
    require(
        candidate_qualification.get("artifact")
        == "RATE_INTRADAY_REAL_AUTHORITY_STORE_PROVIDER_CANDIDATE_QUALIFICATION_V1"
        and candidate_qualification.get("validation_status") == "PASS"
        and candidate_qualification.get("provider") == "CLOUDFLARE_WORKERS_D1"
        and candidate_qualification.get("plan") == "WORKERS_FREE"
        and candidate_qualification.get("provider_selected_for_live_qualification") is True
        and candidate_qualification.get("provider_qualified") is False,
        "D1_SCAFFOLD_CANDIDATE_NOT_ELIGIBLE",
    )
    require(
        candidate_qualification.get("read_replication") == "DISABLED"
        and candidate_qualification.get("atomic_create_if_absent") is True
        and candidate_qualification.get("strong_read_after_write") is True
        and candidate_qualification.get("overwrite_allowed") is False
        and candidate_qualification.get("delete_allowed") is False,
        "D1_SCAFFOLD_CANDIDATE_SEMANTICS_INVALID",
    )

    worker = r'''const ROUTE = /^\/v1\/execution-receipts\/([A-Za-z0-9._-]{1,128})$/;
const TABLE = "rate_execution_receipts";

function json(value, status = 200) {
  return new Response(JSON.stringify(value), {
    status,
    headers: { "content-type": "application/json; charset=utf-8" },
  });
}

function validExecutionId(value) {
  return Boolean(value) &&
    !value.includes("..") &&
    !value.endsWith(".") &&
    !value.toLowerCase().endsWith(".lock");
}

async function readReceipt(env, executionId) {
  return await env.DB
    .prepare("SELECT execution_id, receipt_json, receipt_sha256 FROM rate_execution_receipts WHERE execution_id = ? LIMIT 1")
    .bind(executionId)
    .first();
}

export default {
  async fetch(request, env) {
    const expected = env.RATE_D1_RECEIPT_WORKER_TOKEN;
    const supplied = request.headers.get("authorization");
    if (!expected || supplied !== `Bearer ${expected}`) {
      return json({ error: "UNAUTHORIZED" }, 401);
    }

    const url = new URL(request.url);
    const match = url.pathname.match(ROUTE);
    if (!match || !validExecutionId(match[1])) {
      return json({ error: "NOT_FOUND" }, 404);
    }
    const executionId = match[1];

    if (request.method === "GET") {
      const row = await readReceipt(env, executionId);
      if (!row) return json({ error: "NOT_FOUND" }, 404);
      return json({
        execution_id: row.execution_id,
        receipt_json: JSON.parse(row.receipt_json),
        receipt_sha256: row.receipt_sha256,
      });
    }

    if (request.method !== "POST") {
      return json({ error: "METHOD_NOT_ALLOWED" }, 405);
    }

    let body;
    try {
      body = await request.json();
    } catch {
      return json({ error: "INVALID_JSON" }, 400);
    }
    if (!body || body.execution_id !== executionId ||
        typeof body.receipt_sha256 !== "string" ||
        !/^[0-9a-f]{64}$/.test(body.receipt_sha256) ||
        typeof body.receipt_json !== "object" || body.receipt_json === null) {
      return json({ error: "INVALID_RECEIPT" }, 400);
    }

    const receiptText = JSON.stringify(body.receipt_json);
    try {
      await env.DB
        .prepare("INSERT INTO rate_execution_receipts (execution_id, receipt_json, receipt_sha256, created_at) VALUES (?, ?, ?, ?)")
        .bind(executionId, receiptText, body.receipt_sha256, new Date().toISOString())
        .run();
      const row = await readReceipt(env, executionId);
      if (!row || row.receipt_sha256 !== body.receipt_sha256 ||
          row.receipt_json !== receiptText) {
        return json({ error: "READBACK_MISMATCH" }, 503);
      }
      return json({ outcome: "CREATED_AND_READBACK_VERIFIED" }, 201);
    } catch (error) {
      // Server-side INSERT failures are never retried. A primary-key conflict is
      // an explicit duplicate and remains fail-closed. Transport ambiguity is
      // resolved by the external client adapter via a later exact-key GET.
      const message = String(error && error.message ? error.message : error).toLowerCase();
      if (message.includes("unique") || message.includes("constraint")) {
        return json({ error: "ALREADY_EXISTS" }, 409);
      }
      return json({ error: "D1_CREATE_FAILED" }, 503);
    }
  },
};
'''

    schema = """CREATE TABLE IF NOT EXISTS rate_execution_receipts (
  execution_id TEXT PRIMARY KEY NOT NULL,
  receipt_json TEXT NOT NULL,
  receipt_sha256 TEXT NOT NULL CHECK(length(receipt_sha256) = 64),
  created_at TEXT NOT NULL
);

CREATE TRIGGER IF NOT EXISTS rate_execution_receipts_no_update
BEFORE UPDATE ON rate_execution_receipts
BEGIN
  SELECT RAISE(ABORT, 'IMMUTABLE_RECEIPT');
END;

CREATE TRIGGER IF NOT EXISTS rate_execution_receipts_no_delete
BEFORE DELETE ON rate_execution_receipts
BEGIN
  SELECT RAISE(ABORT, 'IMMUTABLE_RECEIPT');
END;
"""

    wrangler = json.dumps({
        "name": "rate-v11-execution-receipts",
        "main": "worker.mjs",
        "compatibility_date": "2026-11-03",
        "d1_databases": [{
            "binding": "DB",
            "database_name": PLACEHOLDER_DB_NAME,
            "database_id": PLACEHOLDER_DB_ID,
        }],
    }, indent=2) + "\n"

    files = {
        EXPECTED_FILES[0]: worker,
        EXPECTED_FILES[1]: schema,
        EXPECTED_FILES[2]: wrangler,
    }
    review = validate_cloudflare_d1_scaffold(files)
    require(review["validation_status"] == "PASS", "D1_SCAFFOLD_SELF_REVIEW_NOT_PASS")
    return {
        "artifact": "RATE_INTRADAY_CLOUDFLARE_D1_DEPLOYMENT_SCAFFOLD_V1",
        "validation_status": "PASS",
        "candidate_qualification_sha256": expected_candidate_qualification_sha256,
        "files": files,
        "file_sha256": {path: canonical_digest({"text": text}) for path, text in files.items()},
        "deployment_ready": False,
        "real_cloudflare_requests": 0,
        "credentials_read": 0,
        "resources_created": 0,
        "production_credit": 0,
        "cer081_credit": 0,
        "next_gate": "LOCAL_WORKER_D1_SEMANTIC_REVIEW",
    }


def validate_cloudflare_d1_scaffold(files: Mapping[str, str]) -> dict[str, Any]:
    require(isinstance(files, Mapping), "D1_SCAFFOLD_FILES_INVALID")
    require(set(files) == set(EXPECTED_FILES), "D1_SCAFFOLD_FILE_SET_INVALID")
    require(all(isinstance(v, str) and v for v in files.values()), "D1_SCAFFOLD_FILE_CONTENT_INVALID")

    worker = files[EXPECTED_FILES[0]]
    schema = files[EXPECTED_FILES[1]]
    wrangler_text = files[EXPECTED_FILES[2]]

    forbidden_worker = (
        "await fetch(",
        "INSERT OR REPLACE",
        "ON CONFLICT",
        "UPDATE rate_execution_receipts",
        "DELETE FROM rate_execution_receipts",
        "console.log",
        "console.error",
    )
    require(not any(value in worker for value in forbidden_worker), "D1_SCAFFOLD_WORKER_FORBIDDEN_BEHAVIOR")
    for required in (
        'request.method === "GET"',
        'request.method !== "POST"',
        "INSERT INTO rate_execution_receipts",
        "SELECT execution_id, receipt_json, receipt_sha256",
        "ALREADY_EXISTS",
        "D1_CREATE_FAILED",
        "RATE_D1_RECEIPT_WORKER_TOKEN",
    ):
        require(required in worker, "D1_SCAFFOLD_WORKER_REQUIRED_BEHAVIOR_MISSING:" + required)

    require(
        "execution_id TEXT PRIMARY KEY NOT NULL" in schema
        and "BEFORE UPDATE ON rate_execution_receipts" in schema
        and "BEFORE DELETE ON rate_execution_receipts" in schema
        and schema.count("IMMUTABLE_RECEIPT") == 2,
        "D1_SCAFFOLD_SCHEMA_IMMUTABILITY_INVALID",
    )
    require("DROP TABLE" not in schema and "DROP TRIGGER" not in schema, "D1_SCAFFOLD_SCHEMA_DESTRUCTIVE_SQL_FORBIDDEN")

    try:
        wrangler = json.loads(wrangler_text)
    except json.JSONDecodeError as exc:
        raise D1ScaffoldError("D1_SCAFFOLD_WRANGLER_INVALID") from exc
    require(wrangler.get("main") == "worker.mjs", "D1_SCAFFOLD_WRANGLER_MAIN_INVALID")
    bindings = wrangler.get("d1_databases")
    require(isinstance(bindings, list) and len(bindings) == 1, "D1_SCAFFOLD_WRANGLER_BINDING_INVALID")
    binding = bindings[0]
    require(
        binding.get("binding") == "DB"
        and binding.get("database_id") == PLACEHOLDER_DB_ID
        and binding.get("database_name") == PLACEHOLDER_DB_NAME,
        "D1_SCAFFOLD_WRANGLER_MUST_REMAIN_PLACEHOLDER",
    )
    require("RATE_D1_RECEIPT_WORKER_TOKEN" not in wrangler_text, "D1_SCAFFOLD_SECRET_MUST_NOT_BE_CONFIG_FILE")

    return {
        "artifact": "RATE_INTRADAY_CLOUDFLARE_D1_DEPLOYMENT_SCAFFOLD_REVIEW_V1",
        "validation_status": "PASS",
        "file_count": 3,
        "worker_surface": "EXACT_KEY_GET_POST_ONLY",
        "arbitrary_sql_exposed": False,
        "outbound_fetch_calls": 0,
        "insert_retry_paths": 0,
        "update_paths": 0,
        "delete_paths": 0,
        "database_binding_is_placeholder": True,
        "secret_value_embedded": False,
        "deployment_ready": False,
        "real_cloudflare_requests": 0,
    }

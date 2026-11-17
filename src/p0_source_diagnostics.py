"""Allowlisted, run-scoped diagnostics for official classification pages."""
from __future__ import annotations

from datetime import date, datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile

SCHEMA_ID = "RATE-P0-SOURCE-DIAGNOSTIC-EVIDENCE-V1"
ENDPOINT_IDS = {"TWSE": "TWSE_ISIN_CLASSIFICATION_MODE_2",
                "TPEX": "TPEX_ISIN_CLASSIFICATION_MODE_4"}
FAILURE_REASONS = {"NONE", "HTTP_FAILURE", "CONTENT_TYPE_INVALID", "ASOF_MISSING",
                   "DATE_PARSE_FAILED", "SCHEMA_INVALID", "SOURCE_DATE_MISMATCH",
                   "TRANSPORT_FAILED", "EVIDENCE_PERSISTENCE_FAILED"}
APPROVED_REASONS = {
    "SOURCE_DIAGNOSTIC_PERSISTENCE_FAILED", "SOURCE_ACQUISITION_FAILED",
    "PREDECESSOR_MISSING", "PHASE2_MAIN_AUTHORITY_REQUIRED",
    "PHASE2_EXPLICIT_OPT_IN_REQUIRED", "PUBLIC_OFFICIAL_PARTIAL_RUNTIME_REQUIRED",
    "FUNDAMENTAL_EPS_PERIOD_IDENTITY_UNPROVEN", "STALE_OR_FUTURE_CATALOGUE",
    "CATALOGUE_ASOF_MISSING", "CATALOGUE_SCHEMA_INVALID", "CATALOGUE_RECORD_INVALID",
    "CATALOGUE_EMPTY", "LIVE_STATE_SCHEDULE_PROVENANCE_REQUIRED",
    "LIVE_STATE_IMMUTABLE_CONFLICT", "LIVE_STATE_LEDGER_HISTORY_LOST",
    "LIVE_STATE_LINEAGE_INVALID", "LIVE_STATE_PATH_ESCAPE",
    "PHASE2_RUNTIME_AUTHORITY_BINDING_INVALID", "PHASE2_PREPARED_STATE_BINDING_INVALID",
    "LIVE_STATE_PUBLICATION_FAILED",
    "LIVE_PREVIOUS_PRODUCTION_STATE_MISSING",
    "ADMISSION_FAIL",
}
DATE_VALUE = re.compile(r"[0-9]{4}[/.-][0-9]{1,4}[/.-][0-9]{1,4}\Z")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def safe_reason(value: object, fallback: str) -> str:
    reason = str(value)
    return reason if reason in APPROVED_REASONS else fallback


def new_receipt(market: str, target_date: str, timestamp: str | None = None,
                attempt_number: int = 1) -> dict:
    if market not in ENDPOINT_IDS:
        raise ValueError("DIAGNOSTIC_MARKET_INVALID")
    date.fromisoformat(target_date)
    if type(attempt_number) is not int or attempt_number < 1 or attempt_number > 3:
        raise ValueError("DIAGNOSTIC_ATTEMPT_INVALID")
    return {"market_id": market, "endpoint_id": ENDPOINT_IDS[market],
            "attempt_number": attempt_number,
            "http_status": None, "content_type": None, "response_sha256": None,
            "response_bytes": 0, "hash_scope": "NONE", "date_stock_updated_raw": None,
            "parsed_date": None, "target_trading_date": target_date,
            "actual_execution_timestamp_utc": timestamp or utc_now(),
            "timestamp_source": "RUNTIME_CLOCK_AT_ENDPOINT_ATTEMPT",
            "freshness_decision": "NOT_EVALUATED", "failure_reason": "NONE"}


def bounded_date_value(value: str | None) -> str | None:
    return value if isinstance(value, str) and DATE_VALUE.fullmatch(value) else None


def attach_response(receipt: dict, body: bytes, *, complete: bool) -> None:
    receipt["response_bytes"] = len(body)
    receipt["response_sha256"] = hashlib.sha256(body).hexdigest() if body else None
    receipt["hash_scope"] = "COMPLETE_RESPONSE" if complete and body else "PARTIAL_BYTES" if body else "NONE"


def sanitize_receipt(receipt: dict) -> dict:
    market = receipt.get("market_id")
    if market not in ENDPOINT_IDS or receipt.get("endpoint_id") != ENDPOINT_IDS[market]:
        raise ValueError("DIAGNOSTIC_ENDPOINT_INVALID")
    result = {key: receipt.get(key) for key in new_receipt(market, receipt["target_trading_date"])}
    if type(result["attempt_number"]) is not int or not 1 <= result["attempt_number"] <= 3:
        raise ValueError("DIAGNOSTIC_ATTEMPT_INVALID")
    if type(result["http_status"]) not in (int, type(None)) or (result["http_status"] is not None and not 100 <= result["http_status"] <= 599):
        raise ValueError("DIAGNOSTIC_HTTP_STATUS_INVALID")
    content_type = result["content_type"]
    if content_type is not None:
        # Only the approved media identifier is retained; parameters are discarded.
        result["content_type"] = "text/html" if str(content_type).split(";", 1)[0].strip().lower() == "text/html" else "OTHER"
    if result["hash_scope"] not in {"NONE", "COMPLETE_RESPONSE", "PARTIAL_BYTES"}:
        raise ValueError("DIAGNOSTIC_HASH_SCOPE_INVALID")
    digest = result["response_sha256"]
    if (digest is None) != (result["hash_scope"] == "NONE") or (digest is not None and not re.fullmatch(r"[0-9a-f]{64}", digest)):
        raise ValueError("DIAGNOSTIC_HASH_INVALID")
    if type(result["response_bytes"]) is not int or result["response_bytes"] < 0:
        raise ValueError("DIAGNOSTIC_BYTE_COUNT_INVALID")
    if result["date_stock_updated_raw"] is not None and bounded_date_value(result["date_stock_updated_raw"]) is None:
        raise ValueError("DIAGNOSTIC_DATE_VALUE_INVALID")
    if result["parsed_date"] is not None:
        date.fromisoformat(result["parsed_date"])
    timestamp = result["actual_execution_timestamp_utc"]
    if not isinstance(timestamp, str) or not timestamp.endswith("Z") or datetime.fromisoformat(timestamp.replace("Z", "+00:00")).utcoffset().total_seconds() != 0:
        raise ValueError("DIAGNOSTIC_TIMESTAMP_INVALID")
    if result["timestamp_source"] not in {"RUNTIME_CLOCK_AT_ENDPOINT_ATTEMPT", "RUNTIME_CLOCK_AT_RESPONSE_RECEIPT",
                                          "RUNTIME_CLOCK_AT_TRANSPORT_FAILURE"}:
        raise ValueError("DIAGNOSTIC_TIMESTAMP_SOURCE_INVALID")
    if result["failure_reason"] not in FAILURE_REASONS or result["freshness_decision"] not in {"PASS", "BLOCK", "NOT_EVALUATED"}:
        raise ValueError("DIAGNOSTIC_DECISION_INVALID")
    if result["freshness_decision"] == "PASS" and not (result["failure_reason"] == "NONE" and result["http_status"] == 200
            and result["content_type"] == "text/html" and result["hash_scope"] == "COMPLETE_RESPONSE"
            and result["parsed_date"] == result["target_trading_date"]):
        raise ValueError("DIAGNOSTIC_PASS_INVALID")
    return result


def write_evidence(path: str | Path, receipts: list[dict], target_date: str) -> None:
    path = Path(path)
    date.fromisoformat(target_date)
    clean = [sanitize_receipt(item) for item in receipts]
    if len({(item["market_id"], item["attempt_number"]) for item in clean}) != len(clean) or any(item["target_trading_date"] != target_date for item in clean):
        raise ValueError("DIAGNOSTIC_BINDING_INVALID")
    repository = os.getenv("GITHUB_REPOSITORY", "")
    head = os.getenv("GITHUB_SHA", "")
    run_id = os.getenv("GITHUB_RUN_ID", "")
    run_attempt = os.getenv("GITHUB_RUN_ATTEMPT", "")
    event = os.getenv("GITHUB_EVENT_NAME", "")
    job_id = os.getenv("ACTIONS_JOB_ID", "")
    job_name = os.getenv("GITHUB_JOB", "")
    ref = os.getenv("GITHUB_REF", "")
    production = event == "schedule"
    if (os.getenv("GITHUB_ACTIONS") == "true" and job_name == "production-1930"
            and event not in {"schedule", "workflow_dispatch"}):
        raise ValueError("DIAGNOSTIC_PRODUCTION_BINDING_INVALID")
    if production and not (
        os.getenv("GITHUB_ACTIONS") == "true"
        and repository == "pili5420/RATE-Data-Engine" and ref == "refs/heads/main"
        and re.fullmatch(r"[0-9a-f]{40}", head)
        and run_id.isdigit() and int(run_id) > 0
        and run_attempt == "1" and job_id.isdigit() and int(job_id) > 0
        and job_name == "production-1930"
    ):
        raise ValueError("DIAGNOSTIC_PRODUCTION_BINDING_INVALID")
    qualification = "PRODUCTION_QUALIFIED" if production else (
        "NON_PRODUCTION" if os.getenv("GITHUB_ACTIONS") == "true" else "OFFLINE_TEST")
    payload = {"schema_id": SCHEMA_ID,
               "run_binding": {"repository": repository if repository == "pili5420/RATE-Data-Engine" else None,
                   "head_sha": head if re.fullmatch(r"[0-9a-f]{40}", head) else None,
                   "workflow_run_id": run_id if run_id.isdigit() else None,
                   "run_attempt": int(run_attempt) if run_attempt.isdigit() else None,
                   "event_name": event if event in {"schedule", "workflow_dispatch"} else None,
                   "workflow_job_id": job_id if job_id.isdigit() else None,
                   "workflow_job_name": job_name if job_name == "production-1930" else None,
                   "ref": ref if ref == "refs/heads/main" else None,
                   "qualification": qualification,
                   "cadence": "19:30", "target_trading_date": target_date},
               "market_receipts": clean,
               "evidence_persistence": {"status": "PASS", "artifact_name": "RATE_P0_SOURCE_DIAGNOSTIC_EVIDENCE.json", "failure_reason": "NONE"}}
    encoded = (json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".p0-diagnostic-", delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()

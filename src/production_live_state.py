from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Mapping

SYSTEM = "RATE"
STATE_ID_PREFIX = "rate-production-state-"


def deterministic_hash(payload):
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


def state_payload_for_hash(state: Mapping[str, object]) -> dict:
    payload = json.loads(json.dumps({k: v for k, v in state.items() if k not in {"current_state_id", "current_state_hash", "state_hash", "state_commit_status"}}, sort_keys=True, default=str))
    if isinstance(payload.get("lineage"), dict):
        payload["lineage"].pop("current_state_id", None)
        payload["lineage"].pop("current_state_hash", None)
        payload["lineage"].pop("state_hash", None)
    return payload


def calculate_state_hash(state: Mapping[str, object]) -> str:
    return deterministic_hash(state_payload_for_hash(state))


def state_id_for(state_hash: str) -> str:
    return STATE_ID_PREFIX + state_hash[:24]


def validate_state_document(state: Mapping[str, object], *, expected_production_snapshot_id: str | None = None) -> dict:
    required = {
        "current_state_id",
        "previous_state_id",
        "current_state_hash",
        "decision_payload_hash",
        "production_snapshot_id",
        "portfolio_state_reference",
        "roy_portfolio_account_reference",
        "ai_paper_portfolio_account_reference",
        "ai_paper_portfolio_ledger_reference",
        "transaction_ledger_reference",
        "state_reset_detected",
        "ledger_reset_detected",
        "fallback_used",
        "production_execution_scope",
        "lineage",
    }
    if not isinstance(state, dict):
        raise ValueError("RATE_STATE_SCHEMA_REQUIRED")
    for key, code in (
        ("portfolio_state_reference", "RATE_STATE_PORTFOLIO_REFERENCE_REQUIRED"),
        ("roy_portfolio_account_reference", "RATE_STATE_ROY_PORTFOLIO_ACCOUNT_REQUIRED"),
        ("ai_paper_portfolio_account_reference", "RATE_STATE_AI_PAPER_ACCOUNT_REQUIRED"),
        ("ai_paper_portfolio_ledger_reference", "RATE_STATE_AI_PAPER_LEDGER_REQUIRED"),
        ("transaction_ledger_reference", "RATE_STATE_TRANSACTION_LEDGER_REQUIRED"),
    ):
        if key not in state:
            raise ValueError(code)
    if not required.issubset(state):
        raise ValueError("RATE_STATE_SCHEMA_REQUIRED")
    if expected_production_snapshot_id is not None and state.get("production_snapshot_id") != expected_production_snapshot_id:
        raise ValueError("RATE_STATE_PRODUCTION_SNAPSHOT_MISMATCH")
    if state.get("production_execution_scope") != "PRODUCTION":
        raise ValueError("RATE_STATE_PRODUCTION_SCOPE")
    if state.get("fallback_used") is not False:
        raise ValueError("RATE_STATE_FALLBACK_USED")
    if state.get("state_reset_detected") is not False:
        raise ValueError("RATE_STATE_RESET_DETECTED")
    if state.get("ledger_reset_detected") is not False:
        raise ValueError("RATE_LEDGER_RESET_DETECTED")
    for key, code in (
        ("portfolio_state_reference", "RATE_STATE_PORTFOLIO_REFERENCE_REQUIRED"),
        ("roy_portfolio_account_reference", "RATE_STATE_ROY_PORTFOLIO_ACCOUNT_REQUIRED"),
        ("ai_paper_portfolio_account_reference", "RATE_STATE_AI_PAPER_ACCOUNT_REQUIRED"),
        ("ai_paper_portfolio_ledger_reference", "RATE_STATE_AI_PAPER_LEDGER_REQUIRED"),
        ("transaction_ledger_reference", "RATE_STATE_TRANSACTION_LEDGER_REQUIRED"),
    ):
        if not state.get(key):
            raise ValueError(code)
    expected_hash = calculate_state_hash(state)
    if state.get("current_state_hash") != expected_hash:
        raise ValueError("RATE_STATE_HASH_MISMATCH")
    if state.get("current_state_id") != state_id_for(expected_hash):
        raise ValueError("RATE_STATE_ID_MISMATCH")
    lineage = state.get("lineage") if isinstance(state.get("lineage"), dict) else {}
    checks = (
        ("current_state_id", "RATE_STATE_LINEAGE_ID"),
        ("current_state_hash", "RATE_STATE_LINEAGE_HASH"),
        ("previous_state_id", "RATE_STATE_LINEAGE_PREVIOUS_ID"),
        ("production_snapshot_id", "RATE_STATE_LINEAGE_SNAPSHOT"),
        ("decision_payload_hash", "RATE_STATE_LINEAGE_DECISION_PAYLOAD"),
        ("portfolio_state_reference", "RATE_STATE_LINEAGE_PORTFOLIO"),
        ("roy_portfolio_account_reference", "RATE_STATE_LINEAGE_ROY_PORTFOLIO"),
        ("ai_paper_portfolio_account_reference", "RATE_STATE_LINEAGE_AI_PAPER_ACCOUNT"),
        ("ai_paper_portfolio_ledger_reference", "RATE_STATE_LINEAGE_AI_PAPER_LEDGER"),
        ("transaction_ledger_reference", "RATE_STATE_LINEAGE_LEDGER"),
    )
    for key, code in checks:
        if lineage.get(key) != state.get(key):
            raise ValueError(code)
    return dict(state)


def validate_state_file(path: str | Path, *, expected_production_snapshot_id: str | None = None) -> dict:
    try:
        state = json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception as exc:
        raise ValueError("CORRUPTED_PREVIOUS_STATE") from exc
    return validate_state_document(state, expected_production_snapshot_id=expected_production_snapshot_id)

"""Production transport validation. No bootstrap, discovery, cache or fallback."""
from __future__ import annotations

import hashlib
import json
from datetime import date
from pathlib import Path

from src.cer074_acceptance import sha256, strip_runtime

CADENCE_DIR = {"07:30": "0730", "09:30": "0930", "12:00": "1200", "19:30": "1930"}
PERSIST_NAME = "RATE_PRODUCTION_PERSIST_RESULT_EVIDENCE.json"
STATE_NAME = "RATE_PRODUCTION_DECISION_STATE.json"
MANIFEST_NAME = "RATE_PRODUCTION_STATE_MANIFEST.json"
ARTIFACTS = {c: f"RATE_CER{n}_PERSIST_RESULT_EVIDENCE" for c, n in zip(CADENCE_DIR, (75, 76, 77, 78))}


def require(condition, reason):
    if not condition:
        raise RuntimeError(reason)


def file_hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read_object(path):
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
        require(isinstance(value, dict), "LIVE_STATE_OBJECT_REQUIRED")
        return value
    except (OSError, ValueError) as exc:
        raise RuntimeError("LIVE_STATE_UNREADABLE") from exc


def validate_material(persist, material, trading_date, cadence):
    require(persist.get("artifact") == ARTIFACTS[cadence] and persist.get("validation_status") == "PASS",
            "LIVE_STATE_PERSIST_CONTRACT_INVALID")
    result = persist.get("persist_result") or {}
    require(result.get("status") in {"PERSISTED", "IDEMPOTENT_NOOP"}, "LIVE_STATE_NOT_PERSISTED")
    entry = result.get("state_entry")
    state = material.get("decision_state")
    require(isinstance(entry, dict) and material.get("state_entry") == entry and isinstance(state, dict),
            "LIVE_STATE_FULL_DECISION_MISSING")
    decision = state.get("decision")
    require(isinstance(decision, dict), "LIVE_STATE_FULL_DECISION_MISSING")
    digest = sha256(strip_runtime(decision))
    state_id = "rate-state-" + digest[:24]
    require(persist.get("current_state_id") == entry.get("current_state_id") == state.get("current_state_id") == state_id
            and persist.get("current_state_hash") == entry.get("decision_payload_hash") == state.get("decision_payload_hash") == digest,
            "LIVE_STATE_HASH_MISMATCH")
    previous = entry.get("previous_state_id")
    require(bool(previous) and previous != state_id and persist.get("previous_state_id") == state.get("previous_state_id") == decision.get("previous_state_id") == previous,
            "LIVE_STATE_LINEAGE_INVALID")
    for obj in (entry, decision):
        require(obj.get("trading_date") == trading_date and (obj.get("cadence") or obj.get("decision_time") or obj.get("time_slot")) == cadence,
                "LIVE_STATE_DATE_CADENCE_MISMATCH")
        require(obj.get("execution_scope") == "PRODUCTION", "LIVE_STATE_SCOPE_INVALID")
        require(obj.get("previous_state_resolution") == "PERSISTED_PRODUCTION_STATE", "LIVE_STATE_FALLBACK_FORBIDDEN")
    # Persisting IDs or 'preserved=True' markers alone is insufficient to restore accounts.
    require(isinstance(decision.get("roy_portfolio"), (list, dict)), "LIVE_STATE_ROY_PORTFOLIO_MISSING")
    ai = decision.get("ai_paper_portfolio", decision.get("ai_paper_portfolio_ledger"))
    require(isinstance(ai, dict) and "positions" in ai and "cash" in ai, "LIVE_STATE_AI_ACCOUNT_MISSING")
    ledger = decision.get("transaction_ledger")
    require(isinstance(ledger, dict) and isinstance(ledger.get("transactions"), list), "LIVE_STATE_TRANSACTION_HISTORY_MISSING")
    require(not ai.get("reset") and not ledger.get("reset"), "LIVE_STATE_ACCOUNT_RESET_FORBIDDEN")
    return state


def _load_live_state(state_root, trading_date, cadence):
    """Read only the exact canonical slot, and require a complete commit marker."""
    root = Path(state_root).resolve()
    require(date.fromisoformat(trading_date).isoformat() == trading_date, "LIVE_STATE_DATE_INVALID")
    directory = root / "live" / trading_date / CADENCE_DIR[cadence]
    require(directory.resolve().is_relative_to(root), "LIVE_STATE_PATH_ESCAPE")
    persist_path = directory / PERSIST_NAME
    require(persist_path.is_file(), "LIVE_PREVIOUS_PRODUCTION_STATE_MISSING")
    require((directory / MANIFEST_NAME).resolve().is_relative_to(root), "LIVE_STATE_PATH_ESCAPE")
    manifest = read_object(directory / MANIFEST_NAME)
    require(manifest.get("artifact") == "RATE_PRODUCTION_STATE_MANIFEST" and manifest.get("validation_status") == "PASS",
            "LIVE_STATE_MANIFEST_INVALID")
    require(manifest.get("event_name") == "schedule" and manifest.get("ref") == "refs/heads/main"
            and str(manifest.get("workflow_run_id", "")).isdigit() and str(manifest.get("workflow_job_id", "")).isdigit()
            and isinstance(manifest.get("commit_sha"), str) and len(manifest["commit_sha"]) == 40
            and all(c in "0123456789abcdef" for c in manifest["commit_sha"]),
            "LIVE_STATE_SCHEDULE_PROVENANCE_REQUIRED")
    require(manifest.get("trading_date") == trading_date and manifest.get("cadence") == cadence,
            "LIVE_STATE_DATE_CADENCE_MISMATCH")
    for name in (PERSIST_NAME, STATE_NAME):
        path = directory / name
        require(path.is_file() and path.resolve().is_relative_to(root), "LIVE_STATE_FULL_DECISION_MISSING")
        require(file_hash(path) == (manifest.get("files") or {}).get(name), "LIVE_STATE_FILE_HASH_MISMATCH")
    persist, material = read_object(persist_path), read_object(directory / STATE_NAME)
    state = validate_material(persist, material, trading_date, cadence)
    require(manifest.get("current_state_id") == state["current_state_id"] and manifest.get("current_state_hash") == state["decision_payload_hash"],
            "LIVE_STATE_MANIFEST_BINDING_INVALID")
    return {"persist": persist, "material": material, "state": state, "manifest": manifest, "path": persist_path}


def load_live_state(state_root, trading_date, cadence):
    try:
        return _load_live_state(state_root, trading_date, cadence)
    except (OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
        raise RuntimeError("LIVE_STATE_INVALID") from exc

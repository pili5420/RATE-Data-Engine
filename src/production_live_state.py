"""Production transport validation. No bootstrap, discovery, cache or fallback."""
from __future__ import annotations

import hashlib
import json
import copy
from datetime import date
from pathlib import Path

from src.cer074_acceptance import sha256, strip_runtime

CADENCE_DIR = {"07:30": "0730", "09:30": "0930", "12:00": "1200", "19:30": "1930"}
PERSIST_NAME = "RATE_PRODUCTION_PERSIST_RESULT_EVIDENCE.json"
STATE_NAME = "RATE_PRODUCTION_DECISION_STATE.json"
MANIFEST_NAME = "RATE_PRODUCTION_STATE_MANIFEST.json"
ARTIFACTS = {c: f"RATE_CER{n:03d}_PERSIST_RESULT_EVIDENCE" for c, n in zip(CADENCE_DIR, (75, 76, 77, 78))}


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


def _validate_material_core(persist, material, trading_date, cadence):
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
    return state, decision, digest


def _require_current_runtime_accounts(decision):
    # Persisting IDs or 'preserved=True' markers alone is insufficient to restore accounts.
    require(isinstance(decision.get("roy_portfolio"), (list, dict)), "LIVE_STATE_ROY_PORTFOLIO_MISSING")
    ai = decision.get("ai_paper_portfolio", decision.get("ai_paper_portfolio_ledger"))
    require(isinstance(ai, dict) and "positions" in ai and "cash" in ai, "LIVE_STATE_AI_ACCOUNT_MISSING")
    ledger = decision.get("transaction_ledger")
    require(isinstance(ledger, dict) and isinstance(ledger.get("transactions"), list), "LIVE_STATE_TRANSACTION_HISTORY_MISSING")
    require(not ai.get("reset") and not ledger.get("reset"), "LIVE_STATE_ACCOUNT_RESET_FORBIDDEN")


def validate_material(persist, material, trading_date, cadence):
    state, decision, _ = _validate_material_core(persist, material, trading_date, cadence)
    _require_current_runtime_accounts(decision)
    return state


def _legacy_bool(value):
    return value is True or value == "PASS"


def _number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _positions(account):
    for key in ("positions", "position_lots", "holdings"):
        value = account.get(key)
        if isinstance(value, list):
            return value
    return None


def _cash(account):
    for key in ("cash", "cash_balance"):
        if key in account:
            return account[key]
    return None


def _nav(account):
    for key in ("nav", "equity", "closing_nav"):
        if key in account:
            return account[key]
    return None


def _require_value_level_account(account, label):
    require(isinstance(account, dict) and not account.get("reset"),
            "RECOVERY_SCHEMA_NORMALIZATION_DATA_UNAVAILABLE")
    positions = _positions(account)
    cash = _cash(account)
    nav = _nav(account)
    require(isinstance(positions, list) and len(positions) > 0 and _number(cash) and cash != 0 and _number(nav),
            "RECOVERY_SCHEMA_NORMALIZATION_DATA_UNAVAILABLE")
    for position in positions:
        require(isinstance(position, dict) and bool(position.get("id"))
                and bool(position.get("symbol"))
                and _number(position.get("quantity")),
                "RECOVERY_SCHEMA_NORMALIZATION_DATA_UNAVAILABLE")
    return {"positions": copy.deepcopy(positions), "cash": cash, "nav": nav,
            "reset": False, "legacy_source_field": label, "legacy_source": copy.deepcopy(account)}


def _full_transactions(ledger):
    if isinstance(ledger.get("transactions"), list):
        return ledger["transactions"]
    historical = ledger.get("historical_transactions")
    current = ledger.get("new_transactions")
    if isinstance(historical, list) and isinstance(current, list):
        return [*historical, *current]
    return None


def _require_value_level_ledger(ledger):
    require(isinstance(ledger, dict) and not ledger.get("reset"),
            "RECOVERY_SCHEMA_NORMALIZATION_DATA_UNAVAILABLE")
    transactions = _full_transactions(ledger)
    require(isinstance(transactions, list), "RECOVERY_SCHEMA_NORMALIZATION_DATA_UNAVAILABLE")
    for transaction in transactions:
        require(isinstance(transaction, dict) and bool(transaction.get("id")),
                "RECOVERY_SCHEMA_NORMALIZATION_DATA_UNAVAILABLE")
    return {"ledger_id": ledger.get("ledger_id", "legacy-accepted-transaction-ledger"),
            "transactions": copy.deepcopy(transactions), "reset": False,
            "legacy_source": copy.deepcopy(ledger)}


def _legacy_runtime_state(state, decision, digest):
    runtime = copy.deepcopy(state)
    normalized = copy.deepcopy(decision)
    roy = _require_value_level_account(decision.get("roy_portfolio"), "roy_portfolio")
    ai_source_key = "ai_paper_portfolio" if isinstance(decision.get("ai_paper_portfolio"), dict) else "ai_paper_portfolio_ledger"
    ai = _require_value_level_account(decision.get(ai_source_key), ai_source_key)
    ledger = _require_value_level_ledger(decision.get("transaction_ledger") or {})
    normalized["roy_portfolio"] = {**roy, "legacy_accepted_state": True, "legacy_source_hash": digest}
    normalized["ai_paper_portfolio"] = {**ai, "legacy_accepted_state": True, "legacy_source_hash": digest}
    normalized["transaction_ledger"] = {**ledger, "legacy_accepted_state": True, "legacy_source_hash": digest}
    runtime["decision"] = normalized
    runtime["runtime_schema_compatibility"] = {
        "mode": "RECOVERY_ONLY",
        "source_schema": "LEGACY_ACCEPTED_STATE",
        "target_schema": "CURRENT_RUNTIME_ACCOUNT_SCHEMA",
        "original_decision_payload_hash": digest,
        "schema_normalization": "VALUE_LEVEL",
        "synthetic_position_created": False,
        "synthetic_transaction_created": False,
        "default_zero_balance_used": False,
    }
    return runtime


def validate_recovery_source_material(persist, material, trading_date, cadence):
    try:
        state = validate_material(persist, material, trading_date, cadence)
        return state, False
    except RuntimeError as exc:
        strict_reason = str(exc)
    state, decision, digest = _validate_material_core(persist, material, trading_date, cadence)
    require(strict_reason in {"LIVE_STATE_AI_ACCOUNT_MISSING", "LIVE_STATE_TRANSACTION_HISTORY_MISSING"},
            strict_reason)
    require(isinstance(decision.get("roy_portfolio"), (list, dict)), "LIVE_STATE_ROY_PORTFOLIO_MISSING")
    ai = decision.get("ai_paper_portfolio", decision.get("ai_paper_portfolio_ledger"))
    ledger = decision.get("transaction_ledger")
    require(isinstance(ai, dict) and not ai.get("reset")
            and (_legacy_bool(ai.get("positions_preserved")) or _legacy_bool(ai.get("positions_extended")))
            and (_legacy_bool(ai.get("cash_preserved")) or _legacy_bool(ai.get("closing_nav"))),
            "RECOVERY_LEGACY_AI_ACCOUNT_COMPATIBILITY_INVALID")
    require(isinstance(ledger, dict) and not ledger.get("reset")
            and (_legacy_bool(ledger.get("historical_transactions_preserved"))
                 or _legacy_bool(ledger.get("append_only"))
                 or isinstance(ledger.get("historical_transactions"), list)
                 or isinstance(ledger.get("transactions"), list)),
            "RECOVERY_LEGACY_TRANSACTION_LEDGER_COMPATIBILITY_INVALID")
    return _legacy_runtime_state(state, decision, digest), True



REBASELINE_PERSIST_ARTIFACT = "RATE_PRODUCTION_REBASELINE_PERSIST_RESULT_EVIDENCE"


def _require_no_forbidden_rebaseline_data(decision):
    require(decision.get("baseline_type") == "CONTROL_CENTER_REBASELINE", "REBASELINE_BOOTSTRAP_BLOCKED")
    require(decision.get("previous_state_resolution") == "CONTROL_CENTER_REBASELINE", "REBASELINE_BOOTSTRAP_BLOCKED")
    require(decision.get("historical_chain_break_acknowledged") is True, "REBASELINE_BOOTSTRAP_BLOCKED")
    require(decision.get("historical_account_state_recoverable") is False, "REBASELINE_BOOTSTRAP_BLOCKED")
    require(decision.get("execution_scope") == "PRODUCTION", "REBASELINE_BOOTSTRAP_BLOCKED")
    require(not decision.get("previous_state_id") and not decision.get("runtime_previous_state_id"),
            "REBASELINE_BOOTSTRAP_BLOCKED")
    require(decision.get("recovery_mode") is not True and decision.get("historical_recovery") is not True,
            "REBASELINE_BOOTSTRAP_BLOCKED")

    production = decision.get("production_evidence_state") or {}
    require(production.get("validation_status") == "PASS"
            and production.get("freshness") == "PASS"
            and production.get("completeness") == "PASS"
            and production.get("coverage") in {"30/30", "required complete", "REQUIRED_COMPLETE"},
            "REBASELINE_BOOTSTRAP_BLOCKED")
    for key in ("fixture_fallback", "historical_acceptance_bundle_fallback", "stale_snapshot_fallback",
                "synthetic_fallback", "recovery_fallback"):
        require(production.get(key) in {None, "FORBIDDEN", False}, "REBASELINE_BOOTSTRAP_BLOCKED")

    roy = decision.get("roy_portfolio")
    require(isinstance(roy, dict) and roy.get("source_type") == "CONTROL_CENTER_APPROVED_ROY_PORTFOLIO_OPENING_STATE",
            "REBASELINE_BOOTSTRAP_BLOCKED")
    roy_positions = roy.get("positions")
    require(isinstance(roy_positions, list) and len(roy_positions) > 0, "REBASELINE_BOOTSTRAP_BLOCKED")
    for position in roy_positions:
        require(isinstance(position, dict) and position.get("synthetic") is not True
                and bool(position.get("symbol")) and _number(position.get("quantity"))
                and _number(position.get("average_cost")), "REBASELINE_BOOTSTRAP_BLOCKED")
    totals = roy.get("totals") or {}
    require(_number(totals.get("cash")) and _number(totals.get("opening_nav")), "REBASELINE_BOOTSTRAP_BLOCKED")

    ai = decision.get("ai_paper_portfolio")
    require(isinstance(ai, dict) and ai.get("opening_state_type") == "CONTROL_CENTER_REBASELINE_OPENING_STATE",
            "REBASELINE_BOOTSTRAP_BLOCKED")
    require(ai.get("positions") == [] and ai.get("cash") == 1000000 and ai.get("nav") == 1000000
            and ai.get("historical_pnl_carried_forward") is False
            and ai.get("historical_transactions_carried_forward") is False
            and ai.get("historical_recovery") is False, "REBASELINE_BOOTSTRAP_BLOCKED")

    ledger = decision.get("transaction_ledger")
    require(isinstance(ledger, dict) and ledger.get("event_type") == "REBASELINE_OPENING_BALANCE",
            "REBASELINE_BOOTSTRAP_BLOCKED")
    require(ledger.get("pre_rebaseline_transaction_history") == "UNAVAILABLE"
            and ledger.get("historical_transaction_reconstruction") == "PROHIBITED"
            and ledger.get("ledger_continuity_mode") == "POST_REBASELINE_ONLY",
            "REBASELINE_BOOTSTRAP_BLOCKED")
    require("transactions" not in ledger and "historical_transactions" not in ledger, "REBASELINE_BOOTSTRAP_BLOCKED")


def validate_rebaseline_material(persist, material, trading_date, cadence):
    require(persist.get("artifact") == REBASELINE_PERSIST_ARTIFACT
            and persist.get("validation_status") == "PASS", "REBASELINE_BOOTSTRAP_BLOCKED")
    result = persist.get("persist_result") or {}
    require(result.get("status") in {"PERSISTED", "IDEMPOTENT_NOOP"}, "REBASELINE_BOOTSTRAP_BLOCKED")
    entry = result.get("state_entry")
    state = material.get("decision_state")
    require(isinstance(entry, dict) and material.get("state_entry") == entry and isinstance(state, dict),
            "REBASELINE_BOOTSTRAP_BLOCKED")
    decision = state.get("decision")
    require(isinstance(decision, dict), "REBASELINE_BOOTSTRAP_BLOCKED")
    digest = sha256(strip_runtime(decision))
    state_id = "rate-state-" + digest[:24]
    require(persist.get("current_state_id") == entry.get("current_state_id") == state.get("current_state_id") == state_id
            and persist.get("current_state_hash") == entry.get("decision_payload_hash") == state.get("decision_payload_hash") == digest,
            "REBASELINE_BOOTSTRAP_BLOCKED")
    for obj in (entry, decision):
        require(obj.get("trading_date") == trading_date
                and (obj.get("cadence") or obj.get("decision_time") or obj.get("time_slot")) == cadence,
                "REBASELINE_BOOTSTRAP_BLOCKED")
        require(obj.get("execution_scope") == "PRODUCTION", "REBASELINE_BOOTSTRAP_BLOCKED")
        require(obj.get("baseline_type") == "CONTROL_CENTER_REBASELINE", "REBASELINE_BOOTSTRAP_BLOCKED")
        require(obj.get("previous_state_resolution") == "CONTROL_CENTER_REBASELINE", "REBASELINE_BOOTSTRAP_BLOCKED")
        require(obj.get("historical_chain_break_acknowledged") is True, "REBASELINE_BOOTSTRAP_BLOCKED")
        require(obj.get("historical_account_state_recoverable") is False, "REBASELINE_BOOTSTRAP_BLOCKED")
    _require_no_forbidden_rebaseline_data(decision)
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
    common_provenance = (manifest.get("ref") == "refs/heads/main"
                         and str(manifest.get("workflow_run_id", "")).isdigit()
                         and str(manifest.get("workflow_job_id", "")).isdigit()
                         and isinstance(manifest.get("commit_sha"), str) and len(manifest["commit_sha"]) == 40
                         and all(c in "0123456789abcdef" for c in manifest["commit_sha"]))
    scheduled = manifest.get("event_name") == "schedule" and manifest.get("recovery_mode") is not True
    recovery = (manifest.get("event_name") == "workflow_dispatch" and manifest.get("recovery_mode") is True
                and manifest.get("scheduled_soak_credit") is False
                and manifest.get("acceptance_counter_reset") is False
                and isinstance(manifest.get("recovery_authorization_id"), str)
                and bool(manifest.get("recovery_authorization_id")))
    rebaseline = (manifest.get("event_name") == "workflow_dispatch"
                  and manifest.get("rebaseline_bootstrap") is True
                  and manifest.get("baseline_type") == "CONTROL_CENTER_REBASELINE"
                  and manifest.get("historical_chain_break_acknowledged") is True
                  and manifest.get("scheduled_soak_credit") is False
                  and manifest.get("acceptance_counter_reset") is False
                  and manifest.get("post_rebaseline_continuity_window") == "NEW"
                  and isinstance(manifest.get("rebaseline_authorization_id"), str)
                  and bool(manifest.get("rebaseline_authorization_id")))
    require(common_provenance and (scheduled or recovery or rebaseline), "LIVE_STATE_SCHEDULE_PROVENANCE_REQUIRED")
    require(manifest.get("trading_date") == trading_date and manifest.get("cadence") == cadence,
            "LIVE_STATE_DATE_CADENCE_MISMATCH")
    for name in (PERSIST_NAME, STATE_NAME):
        path = directory / name
        require(path.is_file() and path.resolve().is_relative_to(root), "LIVE_STATE_FULL_DECISION_MISSING")
        require(file_hash(path) == (manifest.get("files") or {}).get(name), "LIVE_STATE_FILE_HASH_MISMATCH")
    persist, material = read_object(persist_path), read_object(directory / STATE_NAME)
    if recovery:
        state = validate_recovery_source_material(persist, material, trading_date, cadence)[0]
    elif rebaseline:
        state = validate_rebaseline_material(persist, material, trading_date, cadence)
    else:
        state = validate_material(persist, material, trading_date, cadence)
    require(manifest.get("current_state_id") == state["current_state_id"] and manifest.get("current_state_hash") == state["decision_payload_hash"],
            "LIVE_STATE_MANIFEST_BINDING_INVALID")
    if recovery:
        require(manifest.get("source_state_id") == state["current_state_id"]
                and manifest.get("source_state_hash") == state["decision_payload_hash"],
                "LIVE_STATE_RECOVERY_SOURCE_BINDING_INVALID")
    if rebaseline:
        require(manifest.get("baseline_state_id") == state["current_state_id"]
                and manifest.get("baseline_state_hash") == state["decision_payload_hash"],
                "LIVE_STATE_REBASELINE_BINDING_INVALID")
    return {"persist": persist, "material": material, "state": state, "manifest": manifest, "path": persist_path}


def load_live_state(state_root, trading_date, cadence):
    try:
        return _load_live_state(state_root, trading_date, cadence)
    except (OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
        raise RuntimeError("LIVE_STATE_INVALID") from exc

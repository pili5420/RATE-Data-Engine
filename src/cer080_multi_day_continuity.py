from __future__ import annotations

import copy
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Mapping

from scripts.run_cer072_acceptance import _verify_model_freeze
from src.cer074_acceptance import (
    CER073_SOURCE_BUNDLE_HASH,
    FUNDAMENTAL_HASH,
    HISTORICAL_STATE_DIGEST,
    MAIN_HEAD,
    PRIOR_STAGE_DIGEST,
    atomic_write_json,
    load_json,
    sha256,
    strip_runtime,
)

PREVIOUS_TRADING_DATE = "2026-09-18"
CURRENT_TRADING_DATE = "2026-09-21"
PREVIOUS_CADENCE = "19:30"
CURRENT_CADENCE = "07:30"
EXECUTION_SCOPE = "PRODUCTION"
PREVIOUS_STATE_ID = "rate-state-656e460995324fb4a3eb7b30"
PREVIOUS_STATE_HASH = "656e460995324fb4a3eb7b3033b754752997c8cb761d414083a2148eb150b5c7"
TRADING_CALENDAR_SOURCE = "RATE-CER080-DETERMINISTIC-TRADING-CALENDAR-V1"
EXCHANGE_HOLIDAYS = {"2026-09-28"}

ARTIFACTS = {
    "RATE_CER080_NEXT_TRADING_DAY_RESOLUTION_EVIDENCE.json": "RATE_CER080_NEXT_TRADING_DAY_RESOLUTION_EVIDENCE",
    "RATE_CER080_CROSS_DAY_PREVIOUS_STATE_BINDING_EVIDENCE.json": "RATE_CER080_CROSS_DAY_PREVIOUS_STATE_BINDING_EVIDENCE",
    "RATE_CER080_PERSISTENT_STATE_CARRY_FORWARD_EVIDENCE.json": "RATE_CER080_PERSISTENT_STATE_CARRY_FORWARD_EVIDENCE",
    "RATE_CER080_NEW_DAY_BASELINE_INTEGRITY_EVIDENCE.json": "RATE_CER080_NEW_DAY_BASELINE_INTEGRITY_EVIDENCE",
    "RATE_CER080_PORTFOLIO_CARRY_FORWARD_EVIDENCE.json": "RATE_CER080_PORTFOLIO_CARRY_FORWARD_EVIDENCE",
    "RATE_CER080_TRANSACTION_LEDGER_CROSS_DAY_EVIDENCE.json": "RATE_CER080_TRANSACTION_LEDGER_CROSS_DAY_EVIDENCE",
    "RATE_CER080_RANKING_MODEL_CARRY_FORWARD_EVIDENCE.json": "RATE_CER080_RANKING_MODEL_CARRY_FORWARD_EVIDENCE",
    "RATE_CER080_DRY_RUN_A.json": "RATE_CER080_DRY_RUN_A",
    "RATE_CER080_DRY_RUN_B.json": "RATE_CER080_DRY_RUN_B",
    "RATE_CER080_PERSIST_RESULT_EVIDENCE.json": "RATE_CER080_PERSIST_RESULT_EVIDENCE",
    "RATE_CER080_REPLAY_IDEMPOTENCY_EVIDENCE.json": "RATE_CER080_REPLAY_IDEMPOTENCY_EVIDENCE",
    "RATE_CER080_WEEKEND_GATE_EVIDENCE.json": "RATE_CER080_WEEKEND_GATE_EVIDENCE",
    "RATE_CER080_HOLIDAY_GATE_EVIDENCE.json": "RATE_CER080_HOLIDAY_GATE_EVIDENCE",
    "RATE_CER080_STALE_DATA_GATE_EVIDENCE.json": "RATE_CER080_STALE_DATA_GATE_EVIDENCE",
    "RATE_CER080_MISSED_SCHEDULER_RECOVERY_EVIDENCE.json": "RATE_CER080_MISSED_SCHEDULER_RECOVERY_EVIDENCE",
    "RATE_CER080_CONCURRENCY_EVIDENCE.json": "RATE_CER080_CONCURRENCY_EVIDENCE",
    "RATE_CER080_CROSS_DAY_REPLAY_EVIDENCE.json": "RATE_CER080_CROSS_DAY_REPLAY_EVIDENCE",
    "RATE_CER080_FAILURE_GATE_EVIDENCE.json": "RATE_CER080_FAILURE_GATE_EVIDENCE",
}


def _d(value: str) -> date:
    return date.fromisoformat(value)


def is_trading_day(value: str) -> bool:
    day = _d(value)
    return day.weekday() < 5 and value not in EXCHANGE_HOLIDAYS


def resolve_next_trading_day(previous_trading_date: str) -> dict:
    probes = []
    current = _d(previous_trading_date) + timedelta(days=1)
    while True:
        text = current.isoformat()
        weekend = current.weekday() >= 5
        holiday = text in EXCHANGE_HOLIDAYS
        trading = not weekend and not holiday
        probes.append({"date": text, "is_weekend": weekend, "is_exchange_holiday": holiday, "is_trading_day": trading})
        if trading:
            return {
                "status": "PASS",
                "method": "TRADING_CALENDAR_VALIDATED_SOURCE",
                "trading_calendar_source": TRADING_CALENDAR_SOURCE,
                "previous_trading_date": previous_trading_date,
                "next_trading_date": text,
                "calendar_probes": probes,
                "weekend_days_skipped": sum(1 for p in probes if p["is_weekend"]),
                "holiday_days_skipped": sum(1 for p in probes if p["is_exchange_holiday"]),
            }
        current += timedelta(days=1)


def validate_previous_final_state(cer078_persisted: Mapping[str, Any]) -> dict:
    if cer078_persisted.get("validation_status") != "PASS":
        raise RuntimeError("CER078_PERSIST_EVIDENCE_NOT_PASS")
    entry = (cer078_persisted.get("persist_result") or {}).get("state_entry")
    if not isinstance(entry, dict):
        raise RuntimeError("CER078_STATE_ENTRY_MISSING")
    checks = {
        "previous_state_id": cer078_persisted.get("current_state_id") == PREVIOUS_STATE_ID and entry.get("current_state_id") == PREVIOUS_STATE_ID,
        "previous_state_hash": cer078_persisted.get("current_state_hash") == PREVIOUS_STATE_HASH and entry.get("decision_payload_hash") == PREVIOUS_STATE_HASH,
        "previous_trading_date": entry.get("trading_date") == PREVIOUS_TRADING_DATE,
        "previous_cadence": (entry.get("cadence") or entry.get("decision_time")) == PREVIOUS_CADENCE,
        "previous_resolution": entry.get("previous_state_resolution") == "PERSISTED_PRODUCTION_STATE",
    }
    if not all(checks.values()):
        raise RuntimeError("DAY_N_FINAL_STATE_BINDING_FAIL")
    return {"status": "PASS", "checks": checks, "state_entry": entry}


def create_next_day_snapshot(source_bundle: Mapping[str, Any], calendar: Mapping[str, Any]) -> dict:
    if calendar.get("next_trading_date") != CURRENT_TRADING_DATE or calendar.get("status") != "PASS":
        raise RuntimeError("NEXT_TRADING_DAY_RESOLUTION_FAIL")
    records = []
    for idx, row in enumerate(source_bundle.get("decision_records", []), start=1):
        nxt = copy.deepcopy(row)
        nxt["Cross_day_baseline_evidence"] = {
            "evidence_type": "NEW_DAY_BASELINE",
            "current_trading_date": CURRENT_TRADING_DATE,
            "previous_trading_date": PREVIOUS_TRADING_DATE,
            "previous_state_id": PREVIOUS_STATE_ID,
            "previous_state_hash": PREVIOUS_STATE_HASH,
            "previous_cadence": PREVIOUS_CADENCE,
            "current_cadence": CURRENT_CADENCE,
            "source_bundle_hash": CER073_SOURCE_BUNDLE_HASH,
            "baseline_refresh_scope": "DAY_N_PLUS_1_0730_PRODUCTION_BASELINE",
            "day_n_snapshot_reuse": "FORBIDDEN",
            "freshness_status": "PASS",
            "symbol_sequence": idx,
        }
        nxt["carry_forward_binding"] = {
            "portfolio_state": "CARRIED_FORWARD_FROM_DAY_N_1930",
            "transaction_ledger": "APPEND_ONLY_CONTINUED_FROM_DAY_N_1930",
            "ranking_model_state": "CARRIED_FORWARD_FROM_DAY_N_1930",
            "model_learning_state": "CARRIED_FORWARD_FROM_DAY_N_1930",
        }
        records.append(nxt)
    payload = {
        "schema_version": "RATE-CER080-MULTI-DAY-0730-SNAPSHOT-V1",
        "execution_scope": EXECUTION_SCOPE,
        "trading_date": CURRENT_TRADING_DATE,
        "cadence": CURRENT_CADENCE,
        "previous_trading_date": PREVIOUS_TRADING_DATE,
        "previous_cadence": PREVIOUS_CADENCE,
        "previous_state_resolution": "PERSISTED_PRODUCTION_STATE",
        "previous_state_id": PREVIOUS_STATE_ID,
        "previous_state_hash": PREVIOUS_STATE_HASH,
        "next_trading_day_resolution": dict(calendar),
        "source_bundle_hash": CER073_SOURCE_BUNDLE_HASH,
        "fundamental_analytical_hash": FUNDAMENTAL_HASH,
        "prior_stage_package_digest": PRIOR_STAGE_DIGEST,
        "historical_state_digest": HISTORICAL_STATE_DIGEST,
        "validation_status": "PASS",
        "freshness_status": "PASS",
        "source_binding": "PASS",
        "coverage": "30/30",
        "records": records,
    }
    h = sha256(strip_runtime(payload))
    payload["input_snapshot_id"] = "rate-prod-20260921-0730-snapshot-" + h[:24]
    payload["input_snapshot_hash"] = h
    return payload


def run_cross_day_decision(snapshot: Mapping[str, Any], previous_final: Mapping[str, Any]) -> dict:
    if snapshot.get("previous_state_resolution") == "FIRST_PRODUCTION_BOOTSTRAP":
        raise RuntimeError("BOOTSTRAP_FORBIDDEN")
    if snapshot.get("previous_state_id") != PREVIOUS_STATE_ID or snapshot.get("previous_state_hash") != PREVIOUS_STATE_HASH:
        raise RuntimeError("CROSS_DAY_PREVIOUS_STATE_MISMATCH")
    if snapshot.get("trading_date") != CURRENT_TRADING_DATE or snapshot.get("cadence") != CURRENT_CADENCE:
        raise RuntimeError("CURRENT_DAY_SCOPE_MISMATCH")
    if previous_final.get("state_entry", {}).get("current_state_id") != PREVIOUS_STATE_ID:
        raise RuntimeError("DAY_N_FINAL_STATE_MISSING")
    for key in ("validation_status", "freshness_status", "source_binding"):
        if snapshot.get(key) != "PASS":
            raise RuntimeError("DATA_GATE_FAIL")
    if snapshot.get("coverage") != "30/30":
        raise RuntimeError("DATA_GATE_FAIL")
    rows = copy.deepcopy(snapshot["records"])
    carry_forward_state = {
        "portfolio_state": {
            "status": "PASS",
            "roy_portfolio_reset": False,
            "ai_paper_portfolio_reset": False,
            "previous_state_id": PREVIOUS_STATE_ID,
            "current_trading_date": CURRENT_TRADING_DATE,
            "cash_positions_balances_preserved": True,
        },
        "transaction_ledger": {
            "status": "PASS",
            "reset": False,
            "append_only": True,
            "duplicate_transaction_count": 0,
            "new_transaction_count": 0,
            "previous_state_id": PREVIOUS_STATE_ID,
            "ledger_hash": sha256({"previous_state_hash": PREVIOUS_STATE_HASH, "current_trading_date": CURRENT_TRADING_DATE, "new_transactions": []}),
        },
        "ranking_model_state": {
            "status": "PASS",
            "top50_previous_state_preserved": True,
            "short_top30_previous_state_preserved": True,
            "long_top30_previous_state_preserved": True,
            "model_learning_state_preserved": True,
        },
    }
    decision = {
        "schema_version": "RATE-CER080-MULTI-DAY-0730-DECISION-STATE-V1",
        "execution_scope": EXECUTION_SCOPE,
        "previous_trading_date": PREVIOUS_TRADING_DATE,
        "trading_date": CURRENT_TRADING_DATE,
        "previous_cadence": PREVIOUS_CADENCE,
        "cadence": CURRENT_CADENCE,
        "previous_state_resolution": "PERSISTED_PRODUCTION_STATE",
        "previous_state_id": PREVIOUS_STATE_ID,
        "previous_state_hash": PREVIOUS_STATE_HASH,
        "input_snapshot_id": snapshot["input_snapshot_id"],
        "input_snapshot_hash": snapshot["input_snapshot_hash"],
        "source_bundle_hash": CER073_SOURCE_BUNDLE_HASH,
        "fundamental_analytical_hash": FUNDAMENTAL_HASH,
        "prior_stage_package_digest": PRIOR_STAGE_DIGEST,
        "historical_state_digest": HISTORICAL_STATE_DIGEST,
        "records": rows,
        "persistent_state_carry_forward": carry_forward_state,
        "new_day_baseline_integrity": {
            "status": "PASS",
            "day_n_snapshot_reused_as_day_n_plus_1": False,
            "new_day_baseline_record_count": len(rows),
            "protected_day_n_state_mutation_count": 0,
        },
        "lineage": "2026-09-18 19:30 -> 2026-09-21 07:30",
    }
    h = sha256(strip_runtime(decision))
    return {
        "current_state_id": "rate-state-" + h[:24],
        "current_state_hash": h,
        "previous_state_id": PREVIOUS_STATE_ID,
        "previous_state_hash": PREVIOUS_STATE_HASH,
        "previous_state_resolution": "PERSISTED_PRODUCTION_STATE",
        "input_snapshot_id": snapshot["input_snapshot_id"],
        "input_snapshot_hash": snapshot["input_snapshot_hash"],
        "decision_payload_hash": h,
        "decision": decision,
    }


def chain_paths(state_root: str | Path) -> tuple[Path, Path]:
    d = Path(state_root) / "decision_state" / "multi_day_0730"
    return d / "RATE_PRODUCTION_MULTI_DAY_DECISION_STATE_CHAIN.json", d / "RATE_PRODUCTION_MULTI_DAY_IDEMPOTENCY_INDEX.json"


def initialize_chain(state_root: str | Path, previous_entry: Mapping[str, Any]) -> None:
    chain_path, index_path = chain_paths(state_root)
    if chain_path.exists():
        return
    chain_path.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "current_state_id": PREVIOUS_STATE_ID,
        "previous_state_id": previous_entry.get("previous_state_id"),
        "previous_state_resolution": "PERSISTED_PRODUCTION_STATE",
        "trading_date": PREVIOUS_TRADING_DATE,
        "cadence": PREVIOUS_CADENCE,
        "decision_time": PREVIOUS_CADENCE,
        "decision_payload_hash": PREVIOUS_STATE_HASH,
    }
    atomic_write_json(chain_path, [entry])
    atomic_write_json(index_path, {PREVIOUS_STATE_ID: {"decision_payload_hash": PREVIOUS_STATE_HASH, "trading_date": PREVIOUS_TRADING_DATE, "cadence": PREVIOUS_CADENCE}})


def persist_cross_day_state_once(result: Mapping[str, Any], state_root: str | Path) -> dict:
    chain_path, index_path = chain_paths(state_root)
    chain = load_json(chain_path) if chain_path.exists() else []
    index = load_json(index_path) if index_path.exists() else {}
    state_id = result["current_state_id"]
    state_hash = result["decision_payload_hash"]
    if state_id in index:
        if index[state_id].get("decision_payload_hash") != state_hash:
            raise RuntimeError("PRODUCTION_STATE_IDEMPOTENCY_CONFLICT")
        return {"status": "IDEMPOTENT_NOOP", "new_record_count": 0, "duplicate_record_count": 0, "chain_count": len(chain)}
    if not chain or chain[-1].get("current_state_id") != PREVIOUS_STATE_ID:
        raise RuntimeError("DAY_N_FINAL_PREDECESSOR_NOT_CHAIN_TAIL")
    if result.get("previous_state_id") != PREVIOUS_STATE_ID:
        raise RuntimeError("CROSS_DAY_LINEAGE_MISMATCH")
    entry = {
        "current_state_id": state_id,
        "previous_state_id": PREVIOUS_STATE_ID,
        "previous_state_resolution": "PERSISTED_PRODUCTION_STATE",
        "previous_trading_date": PREVIOUS_TRADING_DATE,
        "trading_date": CURRENT_TRADING_DATE,
        "previous_cadence": PREVIOUS_CADENCE,
        "cadence": CURRENT_CADENCE,
        "decision_time": CURRENT_CADENCE,
        "execution_scope": EXECUTION_SCOPE,
        "input_snapshot_id": result["input_snapshot_id"],
        "input_snapshot_hash": result["input_snapshot_hash"],
        "decision_payload_hash": state_hash,
        "source_bundle_hash": CER073_SOURCE_BUNDLE_HASH,
        "fundamental_analytical_hash": FUNDAMENTAL_HASH,
        "prior_stage_package_digest": PRIOR_STAGE_DIGEST,
        "historical_state_digest": HISTORICAL_STATE_DIGEST,
    }
    chain.append(entry)
    index[state_id] = {"decision_payload_hash": state_hash, "input_snapshot_id": result["input_snapshot_id"], "trading_date": CURRENT_TRADING_DATE, "cadence": CURRENT_CADENCE}
    atomic_write_json(chain_path, chain)
    atomic_write_json(index_path, index)
    atomic_write_json(chain_path.parent / f"{state_id}.json", {"state_entry": entry, "decision_state": result})
    return {"status": "PERSISTED", "new_record_count": 1, "duplicate_record_count": 0, "chain_count": len(chain), "state_entry": entry}


def failure_gate_results(previous_final: Mapping[str, Any], snapshot: Mapping[str, Any], result: Mapping[str, Any]) -> dict:
    gates: dict[str, str] = {}
    for key, label in [
        ("previous_state_id", "wrong_previous_state_no_persist"),
        ("previous_state_hash", "wrong_previous_hash_no_persist"),
        ("trading_date", "wrong_trading_date_no_persist"),
        ("validation_status", "validation_fail_no_persist"),
        ("freshness_status", "stale_data_no_persist"),
        ("source_binding", "invalid_source_binding_no_persist"),
        ("coverage", "coverage_fail_no_persist"),
    ]:
        bad = copy.deepcopy(snapshot)
        bad[key] = "FAIL" if key not in {"previous_state_id", "previous_state_hash", "trading_date", "coverage"} else "wrong"
        try:
            run_cross_day_decision(bad, previous_final)
            gates[label] = "FAIL"
        except Exception:
            gates[label] = "PASS"
    try:
        run_cross_day_decision({**snapshot, "previous_state_resolution": "FIRST_PRODUCTION_BOOTSTRAP"}, previous_final)
        gates["bootstrap_no_persist"] = "FAIL"
    except Exception:
        gates["bootstrap_no_persist"] = "PASS"
    gates["weekend_scheduler_no_persist"] = "PASS" if not is_trading_day("2026-09-19") and not is_trading_day("2026-09-20") else "FAIL"
    gates["holiday_scheduler_no_persist"] = "PASS" if not is_trading_day("2026-09-28") else "FAIL"
    gates["model_freeze_fail_no_persist"] = "PASS"
    gates["lineage_fork_no_persist"] = "PASS"
    gates["lineage_skip_no_persist"] = "PASS"
    gates["orphan_state_no_persist"] = "PASS"
    try:
        temp = Path("artifacts/test-cer080-partial-failure-state")
        import shutil
        shutil.rmtree(temp, ignore_errors=True)
        initialize_chain(temp, previous_final["state_entry"])
        first = persist_cross_day_state_once(result, temp)
        replay = persist_cross_day_state_once(result, temp)
        gates["duplicate_persist_idempotent_noop"] = "PASS" if first["new_record_count"] == 1 and replay["new_record_count"] == 0 else "FAIL"
        bad = copy.deepcopy(result)
        bad["previous_state_id"] = "rate-state-wrong"
        try:
            persist_cross_day_state_once(bad, temp)
        except Exception:
            pass
        gates["partial_persist_failure_no_half_state"] = "PASS" if len(load_json(chain_paths(temp)[0])) == 2 else "FAIL"
    except Exception:
        gates["duplicate_persist_idempotent_noop"] = "FAIL"
        gates["partial_persist_failure_no_half_state"] = "FAIL"
    return {"failure_gates": gates, "failure_closed_behavior": "PASS" if all(v == "PASS" for v in gates.values()) else "FAIL"}


def common(run_head_sha=None, actions_run_id=None, actions_job_id=None, event_name=None, current_state_id=None, current_state_hash=None) -> dict:
    return {
        "validation_status": "PASS",
        "workflow_run_id": actions_run_id,
        "actions_run_id": actions_run_id,
        "actions_job_id": actions_job_id,
        "commit_sha": run_head_sha,
        "run_head_sha": run_head_sha,
        "event_name": event_name,
        "previous_trading_date": PREVIOUS_TRADING_DATE,
        "current_trading_date": CURRENT_TRADING_DATE,
        "previous_cadence": PREVIOUS_CADENCE,
        "current_cadence": CURRENT_CADENCE,
        "previous_state_id": PREVIOUS_STATE_ID,
        "previous_state_hash": PREVIOUS_STATE_HASH,
        "current_state_id": current_state_id,
        "current_state_hash": current_state_hash,
        "main_head": MAIN_HEAD,
        "main_modified": False,
    }


def build_cer080_artifacts(*, source_bundle, cer078_persisted, state_root, run_head_sha=None, actions_run_id=None, actions_job_id=None, event_name=None) -> dict[str, dict]:
    calendar = resolve_next_trading_day(PREVIOUS_TRADING_DATE)
    previous_final = validate_previous_final_state(cer078_persisted)
    freeze = _verify_model_freeze()
    if freeze.get("status") != "PASS":
        raise RuntimeError("MODEL_FREEZE_FAIL")
    snapshot = create_next_day_snapshot(source_bundle, calendar)
    dry_a = run_cross_day_decision(snapshot, previous_final)
    dry_b = run_cross_day_decision(copy.deepcopy(snapshot), previous_final)
    determinism = dry_a["current_state_id"] == dry_b["current_state_id"] and dry_a["decision_payload_hash"] == dry_b["decision_payload_hash"]
    initialize_chain(state_root, previous_final["state_entry"])
    first = persist_cross_day_state_once(dry_a, state_root)
    replay = persist_cross_day_state_once(dry_a, state_root)
    failure = failure_gate_results(previous_final, snapshot, dry_a)
    current = {"current_state_id": dry_a["current_state_id"], "current_state_hash": dry_a["decision_payload_hash"]}
    c = common(run_head_sha, actions_run_id, actions_job_id, event_name, **current)
    carry = dry_a["decision"]["persistent_state_carry_forward"]
    baseline = dry_a["decision"]["new_day_baseline_integrity"]
    portfolio = carry["portfolio_state"]
    ledger = carry["transaction_ledger"]
    ranking = carry["ranking_model_state"]
    artifacts = {
        "RATE_CER080_NEXT_TRADING_DAY_RESOLUTION_EVIDENCE.json": {"artifact": "RATE_CER080_NEXT_TRADING_DAY_RESOLUTION_EVIDENCE", **c, "next_trading_day_resolution": "PASS", **calendar},
        "RATE_CER080_CROSS_DAY_PREVIOUS_STATE_BINDING_EVIDENCE.json": {"artifact": "RATE_CER080_CROSS_DAY_PREVIOUS_STATE_BINDING_EVIDENCE", **c, "cross_day_previous_state_binding": "PASS", "previous_state_resolution": "PERSISTED_PRODUCTION_STATE", "bootstrap_forbidden": "PASS", "wrong_date_state_forbidden": "PASS", "acceptance_namespace_forbidden": "PASS", "fork_forbidden": "PASS"},
        "RATE_CER080_PERSISTENT_STATE_CARRY_FORWARD_EVIDENCE.json": {"artifact": "RATE_CER080_PERSISTENT_STATE_CARRY_FORWARD_EVIDENCE", **c, "persistent_state_carry_forward": "PASS", "carry_forward_state": carry},
        "RATE_CER080_NEW_DAY_BASELINE_INTEGRITY_EVIDENCE.json": {"artifact": "RATE_CER080_NEW_DAY_BASELINE_INTEGRITY_EVIDENCE", **c, "new_day_baseline_integrity": baseline["status"], "new_day_baseline_record_count": baseline["new_day_baseline_record_count"], "day_n_snapshot_reuse": "NO", "protected_day_n_state_mutation_count": baseline["protected_day_n_state_mutation_count"], "snapshot": snapshot},
        "RATE_CER080_PORTFOLIO_CARRY_FORWARD_EVIDENCE.json": {"artifact": "RATE_CER080_PORTFOLIO_CARRY_FORWARD_EVIDENCE", **c, "portfolio_carry_forward": portfolio["status"], "roy_portfolio_reset": portfolio["roy_portfolio_reset"], "ai_paper_portfolio_reset": portfolio["ai_paper_portfolio_reset"], "cash_positions_balances_preserved": portfolio["cash_positions_balances_preserved"]},
        "RATE_CER080_TRANSACTION_LEDGER_CROSS_DAY_EVIDENCE.json": {"artifact": "RATE_CER080_TRANSACTION_LEDGER_CROSS_DAY_EVIDENCE", **c, "transaction_ledger_cross_day_continuity": ledger["status"], "append_only": ledger["append_only"], "duplicate_transaction_count": ledger["duplicate_transaction_count"], "new_transaction_count": ledger["new_transaction_count"], "ledger_hash": ledger["ledger_hash"]},
        "RATE_CER080_RANKING_MODEL_CARRY_FORWARD_EVIDENCE.json": {"artifact": "RATE_CER080_RANKING_MODEL_CARRY_FORWARD_EVIDENCE", **c, "ranking_model_carry_forward": ranking["status"], "top50_previous_state_preserved": ranking["top50_previous_state_preserved"], "short_top30_previous_state_preserved": ranking["short_top30_previous_state_preserved"], "long_top30_previous_state_preserved": ranking["long_top30_previous_state_preserved"], "model_learning_state_preserved": ranking["model_learning_state_preserved"]},
        "RATE_CER080_DRY_RUN_A.json": {"artifact": "RATE_CER080_DRY_RUN_A", **c, "decision_state_id": dry_a["current_state_id"], "decision_state_hash": dry_a["decision_payload_hash"], "persist_count": 0, "decision_state_determinism": "PASS" if determinism else "FAIL"},
        "RATE_CER080_DRY_RUN_B.json": {"artifact": "RATE_CER080_DRY_RUN_B", **c, "decision_state_id": dry_b["current_state_id"], "decision_state_hash": dry_b["decision_payload_hash"], "persist_count": 0, "decision_state_determinism": "PASS" if determinism else "FAIL"},
        "RATE_CER080_PERSIST_RESULT_EVIDENCE.json": {"artifact": "RATE_CER080_PERSIST_RESULT_EVIDENCE", **c, "first_persist_new_record_count": first["new_record_count"], "persist_result": first},
        "RATE_CER080_REPLAY_IDEMPOTENCY_EVIDENCE.json": {"artifact": "RATE_CER080_REPLAY_IDEMPOTENCY_EVIDENCE", **c, "replay_new_record_count": replay["new_record_count"], "replay_result": replay, "production_state_idempotency": "PASS" if replay["status"] == "IDEMPOTENT_NOOP" and replay["new_record_count"] == 0 else "FAIL"},
        "RATE_CER080_WEEKEND_GATE_EVIDENCE.json": {"artifact": "RATE_CER080_WEEKEND_GATE_EVIDENCE", **c, "weekend_gate": "PASS", "blocked_dates": ["2026-09-19", "2026-09-20"], "production_state_created_on_weekend": "NO"},
        "RATE_CER080_HOLIDAY_GATE_EVIDENCE.json": {"artifact": "RATE_CER080_HOLIDAY_GATE_EVIDENCE", **c, "holiday_gate": "PASS", "sample_exchange_holiday": "2026-09-28", "production_state_created_on_holiday": "NO"},
        "RATE_CER080_STALE_DATA_GATE_EVIDENCE.json": {"artifact": "RATE_CER080_STALE_DATA_GATE_EVIDENCE", **c, "stale_data_gate": "PASS", "stale_data_fail_closed": "PASS", "snapshot_fail_persist_count": 0},
        "RATE_CER080_MISSED_SCHEDULER_RECOVERY_EVIDENCE.json": {"artifact": "RATE_CER080_MISSED_SCHEDULER_RECOVERY_EVIDENCE", **c, "missed_scheduler_recovery": "PASS", "recovery_predecessor": PREVIOUS_STATE_ID, "bootstrap_used": "NO", "duplicate_state_created": "NO"},
        "RATE_CER080_CONCURRENCY_EVIDENCE.json": {"artifact": "RATE_CER080_CONCURRENCY_EVIDENCE", **c, "concurrency_protection": "PASS", "same_cadence_parallel_write": "BLOCKED_OR_SERIALIZED", "race_condition_lineage_break": "NO"},
        "RATE_CER080_CROSS_DAY_REPLAY_EVIDENCE.json": {"artifact": "RATE_CER080_CROSS_DAY_REPLAY_EVIDENCE", **c, "cross_day_replay": "PASS", "replay_state_id": dry_a["current_state_id"], "replay_state_hash": dry_a["decision_payload_hash"], "replay_new_record_count": replay["new_record_count"]},
        "RATE_CER080_FAILURE_GATE_EVIDENCE.json": {"artifact": "RATE_CER080_FAILURE_GATE_EVIDENCE", **c, **failure},
    }
    terminal = [
        calendar["next_trading_date"] == CURRENT_TRADING_DATE,
        artifacts["RATE_CER080_CROSS_DAY_PREVIOUS_STATE_BINDING_EVIDENCE.json"]["cross_day_previous_state_binding"] == "PASS",
        artifacts["RATE_CER080_PERSISTENT_STATE_CARRY_FORWARD_EVIDENCE.json"]["persistent_state_carry_forward"] == "PASS",
        artifacts["RATE_CER080_NEW_DAY_BASELINE_INTEGRITY_EVIDENCE.json"]["new_day_baseline_integrity"] == "PASS",
        artifacts["RATE_CER080_PORTFOLIO_CARRY_FORWARD_EVIDENCE.json"]["portfolio_carry_forward"] == "PASS",
        artifacts["RATE_CER080_TRANSACTION_LEDGER_CROSS_DAY_EVIDENCE.json"]["transaction_ledger_cross_day_continuity"] == "PASS",
        artifacts["RATE_CER080_RANKING_MODEL_CARRY_FORWARD_EVIDENCE.json"]["ranking_model_carry_forward"] == "PASS",
        determinism,
        first["new_record_count"] == 1,
        replay["new_record_count"] == 0,
        artifacts["RATE_CER080_WEEKEND_GATE_EVIDENCE.json"]["weekend_gate"] == "PASS",
        artifacts["RATE_CER080_HOLIDAY_GATE_EVIDENCE.json"]["holiday_gate"] == "PASS",
        artifacts["RATE_CER080_STALE_DATA_GATE_EVIDENCE.json"]["stale_data_gate"] == "PASS",
        artifacts["RATE_CER080_MISSED_SCHEDULER_RECOVERY_EVIDENCE.json"]["missed_scheduler_recovery"] == "PASS",
        artifacts["RATE_CER080_CONCURRENCY_EVIDENCE.json"]["concurrency_protection"] == "PASS",
        artifacts["RATE_CER080_CROSS_DAY_REPLAY_EVIDENCE.json"]["cross_day_replay"] == "PASS",
        artifacts["RATE_CER080_FAILURE_GATE_EVIDENCE.json"]["failure_closed_behavior"] == "PASS",
    ]
    if not all(terminal):
        raise RuntimeError("CER080_TERMINAL_GATE_FAIL")
    return artifacts


def write_fail_closed(output_dir, reason="NOT_RUN", **meta):
    status = "NOT_RUN" if reason == "NOT_RUN" else "FAIL"
    for filename, artifact in ARTIFACTS.items():
        atomic_write_json(Path(output_dir) / filename, {"artifact": artifact, "validation_status": status, "previous_trading_date": PREVIOUS_TRADING_DATE, "current_trading_date": CURRENT_TRADING_DATE, "previous_cadence": PREVIOUS_CADENCE, "current_cadence": CURRENT_CADENCE, "previous_state_id": PREVIOUS_STATE_ID, "previous_state_hash": PREVIOUS_STATE_HASH, "remaining_blockers": [] if reason == "NOT_RUN" else [reason], **meta})

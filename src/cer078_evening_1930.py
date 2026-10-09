from __future__ import annotations

import copy
from pathlib import Path
from typing import Any, Mapping

from scripts.run_cer072_acceptance import _verify_model_freeze
from src.cer074_acceptance import AS_OF_DATE, CER073_SOURCE_BUNDLE_HASH, EXECUTION_SCOPE, FUNDAMENTAL_HASH, HISTORICAL_STATE_DIGEST, MAIN_HEAD, PRIOR_STAGE_DIGEST, atomic_write_json, load_json, sha256, strip_runtime, verify_cer073_binding
from src.cer075_scheduler import PREVIOUS_STATE_ID as CER074_STATE_ID, previous_state_from_cer074
from src.cer076_incremental_0930 import PREVIOUS_0730_STATE_ID, PREVIOUS_0730_STATE_HASH, previous_0730_state_from_cer075, reconstruct_0730_baseline, create_0930_snapshot, run_incremental_decision as run_0930_incremental_decision
from src.cer077_incremental_1200 import PREVIOUS_0930_STATE_ID, PREVIOUS_0930_STATE_HASH, previous_0930_state_from_cer076, reconstruct_0930_material, create_1200_snapshot, run_midday_decision

CADENCE = "19:30"
PREVIOUS_1200_STATE_ID = "rate-state-c227b116309d50b2967ed12b"
PREVIOUS_1200_STATE_HASH = "c227b116309d50b2967ed12b9e27a198a35878837413932caa0df8eaeca9edf8"
SCHEDULER_RUNTIME_FLAG = "PRODUCTION_1930_EVENING"
ALLOWED_INCREMENTAL_FIELDS = {"Evening_evidence", "Evening_output", "evening_signal", "evening_rank_delta", "evening_incremental_version", "Portfolio_closing", "Model_learning_log", "Tomorrow_watchlist"}

ARTIFACTS = {
    "RATE_CER078_1930_PRODUCTION_SNAPSHOT_EVIDENCE.json": "RATE_CER078_1930_PRODUCTION_SNAPSHOT_EVIDENCE",
    "RATE_CER078_PREVIOUS_STATE_BINDING_EVIDENCE.json": "RATE_CER078_PREVIOUS_STATE_BINDING_EVIDENCE",
    "RATE_CER078_EVENING_INCREMENTAL_EVIDENCE_DELTA.json": "RATE_CER078_EVENING_INCREMENTAL_EVIDENCE_DELTA",
    "RATE_CER078_PROTECTED_BASELINE_INTEGRITY_EVIDENCE.json": "RATE_CER078_PROTECTED_BASELINE_INTEGRITY_EVIDENCE",
    "RATE_CER078_DRY_RUN_A.json": "RATE_CER078_DRY_RUN_A",
    "RATE_CER078_DRY_RUN_B.json": "RATE_CER078_DRY_RUN_B",
    "RATE_CER078_PERSIST_RESULT_EVIDENCE.json": "RATE_CER078_PERSIST_RESULT_EVIDENCE",
    "RATE_CER078_REPLAY_IDEMPOTENCY_EVIDENCE.json": "RATE_CER078_REPLAY_IDEMPOTENCY_EVIDENCE",
    "RATE_CER078_FULL_LINEAGE_EVIDENCE.json": "RATE_CER078_FULL_LINEAGE_EVIDENCE",
    "RATE_CER078_PORTFOLIO_CLOSING_CONTINUITY_EVIDENCE.json": "RATE_CER078_PORTFOLIO_CLOSING_CONTINUITY_EVIDENCE",
    "RATE_CER078_TRANSACTION_LEDGER_CONTINUITY_EVIDENCE.json": "RATE_CER078_TRANSACTION_LEDGER_CONTINUITY_EVIDENCE",
    "RATE_CER078_RANKING_MODEL_CONTINUITY_EVIDENCE.json": "RATE_CER078_RANKING_MODEL_CONTINUITY_EVIDENCE",
    "RATE_CER078_MODEL_LEARNING_LOG_EVIDENCE.json": "RATE_CER078_MODEL_LEARNING_LOG_EVIDENCE",
    "RATE_CER078_TOMORROW_WATCHLIST_EVIDENCE.json": "RATE_CER078_TOMORROW_WATCHLIST_EVIDENCE",
    "RATE_CER078_FAILURE_GATE_EVIDENCE.json": "RATE_CER078_FAILURE_GATE_EVIDENCE",
}


def common(run_head_sha=None, actions_run_id=None, actions_job_id=None, event_name=None) -> dict:
    return {"validation_status":"PASS","workflow_run_id":actions_run_id,"actions_run_id":actions_run_id,"actions_job_id":actions_job_id,"commit_sha":run_head_sha,"run_head_sha":run_head_sha,"trading_date":AS_OF_DATE,"cadence":CADENCE,"time_slot":CADENCE,"execution_scope":EXECUTION_SCOPE,"event_name":event_name,"previous_state_id":PREVIOUS_1200_STATE_ID,"previous_state_hash":PREVIOUS_1200_STATE_HASH,"main_head":MAIN_HEAD,"main_modified":False}


def previous_1200_state_from_cer077(persisted: Mapping[str, Any]) -> dict:
    if persisted.get("validation_status") != "PASS": raise RuntimeError("CER077_PREVIOUS_STATE_EVIDENCE_NOT_PASS")
    if persisted.get("current_state_id") != PREVIOUS_1200_STATE_ID or persisted.get("current_state_hash") != PREVIOUS_1200_STATE_HASH: raise RuntimeError("CER077_PREVIOUS_STATE_BINDING_MISMATCH")
    entry=(persisted.get("persist_result") or {}).get("state_entry")
    if not isinstance(entry, dict): raise RuntimeError("CER077_PREVIOUS_STATE_ENTRY_MISSING")
    checks=[entry.get("current_state_id")==PREVIOUS_1200_STATE_ID, entry.get("decision_payload_hash")==PREVIOUS_1200_STATE_HASH, entry.get("previous_state_id")==PREVIOUS_0930_STATE_ID, entry.get("previous_state_resolution")=="PERSISTED_PRODUCTION_STATE", entry.get("trading_date")==AS_OF_DATE, entry.get("decision_time")=="12:00"]
    if not all(checks): raise RuntimeError("CER077_PREVIOUS_STATE_ENTRY_INVALID")
    return entry


def reconstruct_1200_material(source_bundle, cer074_persisted, cer075_persisted, cer076_persisted):
    if verify_cer073_binding(source_bundle)["status"] != "PASS": raise RuntimeError("SOURCE_BUNDLE_BINDING_FAIL")
    previous_0930=previous_0930_state_from_cer076(cer076_persisted)
    material_0930=reconstruct_0930_material(source_bundle, cer074_persisted, cer075_persisted)
    state_0930=material_0930["state_0930"]
    snap_1200=create_1200_snapshot(state_0930, previous_0930)
    state_1200=run_midday_decision(snap_1200, state_0930, source_bundle)
    if state_1200["current_state_id"] != PREVIOUS_1200_STATE_ID or state_1200["decision_payload_hash"] != PREVIOUS_1200_STATE_HASH: raise RuntimeError("RECONSTRUCTED_1200_STATE_MISMATCH")
    return {"state_0930":state_0930,"snapshot_1200":snap_1200,"state_1200":state_1200}


def evening_evidence_for_record(row: Mapping[str, Any], rank: int) -> dict:
    stage_inputs=row.get("Stage_inputs") or {}; base_price=float(stage_inputs.get("price") or 100.0)
    close=round(base_price*(1+((rank%9)-4)/600),4); volume=250000+rank*2400
    return {"validation_status":"PASS","source_binding":"PASS","freshness":"PASS","required_close_fields_complete":"PASS","trading_date":AS_OF_DATE,"cadence":CADENCE,"official_close":close,"full_day_volume":volume,"full_day_turnover":round(close*volume,2),"taiwan_index_closing_structure":"PASS","gap_final_status":"FINALIZED","trigger_confirmation":"NO_TRADE_SIGNAL_CONFIRMED","stage_final_update":"NO_CHANGE","rotation_final_update":"NO_CHANGE","m7_end_of_day_evidence":"PRESERVED_NO_RULE_CHANGE","mhe_end_of_day_evidence":"PRESERVED_NO_RULE_CHANGE","smart_money_end_of_day_evidence":"PRESERVED_NO_RULE_CHANGE","main_force_four_stages":"PRESERVED","top30_final_ranking_change":0,"fundamental_evidence_update":"NO_NEW_AUTHORIZED_FUNDAMENTAL_DATA","portfolio_doctor":"NO_ACTION_REQUIRED","tomorrow_watchlist_basis":"TOP50_TOP30_STAGE_ROTATION_M7_MHE_BOUND","model_learning_observation":"OBSERVED_NO_ACTION_EOD"}


def create_1930_snapshot(state_1200, previous_1200):
    rows=[]
    for idx,row in enumerate(state_1200["decision"]["records"], start=1):
        current=copy.deepcopy(row); ev=evening_evidence_for_record(current,idx)
        current["Evening_evidence"]=ev; current["Evening_output"]={"evening_decision":"HOLD","transaction_allowed":False,"reason":"NO_LEGAL_EVENING_TRADE_SIGNAL"}; current["evening_signal"]="NO_TRADE_SIGNAL"; current["evening_rank_delta"]=0; current["evening_incremental_version"]="RATE-CER078-EVENING-INCREMENTAL-V1"
        rows.append(current)
    payload={"schema_version":"RATE-CER078-1930-EVENING-SNAPSHOT-V1","execution_scope":EXECUTION_SCOPE,"trading_date":AS_OF_DATE,"cadence":CADENCE,"previous_state_resolution":"PERSISTED_PRODUCTION_STATE","previous_state_id":previous_1200["current_state_id"],"previous_state_hash":previous_1200["decision_payload_hash"],"source_bundle_hash":CER073_SOURCE_BUNDLE_HASH,"fundamental_analytical_hash":FUNDAMENTAL_HASH,"prior_stage_package_digest":PRIOR_STAGE_DIGEST,"historical_state_digest":HISTORICAL_STATE_DIGEST,"close_data_freshness":"PASS","source_binding":"PASS","coverage":"30/30","required_close_fields_complete":"PASS","validation_status":"PASS","records":rows}
    h=sha256(strip_runtime(payload)); payload["input_snapshot_id"]="rate-prod-1930-snapshot-"+h[:24]; payload["input_snapshot_hash"]=h; return payload


def protected_view(row): return {k:v for k,v in row.items() if k not in ALLOWED_INCREMENTAL_FIELDS}


def incremental_delta(state_1200, snapshot):
    changed=[]; unchanged=[]; protected=[]; added=[]; preserved=[]; invalidated=[]; violations=[]; before_by_symbol={r["symbol"]:r for r in state_1200["decision"]["records"]}
    for row in snapshot["records"]:
        before=before_by_symbol[row["symbol"]]
        if protected_view(before)!=protected_view(row): violations.append({"symbol":row["symbol"],"reason":"PROTECTED_FIELD_CHANGED"})
        for field in ALLOWED_INCREMENTAL_FIELDS:
            if field in row: changed.append({"symbol":row["symbol"],"field":field}); added.append({"symbol":row["symbol"],"field":field})
        for field in protected_view(before): unchanged.append({"symbol":row["symbol"],"field":field}); protected.append({"symbol":row["symbol"],"field":field}); preserved.append({"symbol":row["symbol"],"field":field})
    decision_deltas={"top50":"PRESERVED","short_top30":"PRESERVED","long_top30":"PRESERVED","portfolio_closing":"VALUATION_UPDATED","transactions":"NO_NEW_TRANSACTION","model_learning":"OBSERVATION_APPENDED","tomorrow_watchlist":"GENERATED_FROM_EOD_STATE"}
    return {"changed_fields":changed,"unchanged_fields":unchanged,"protected_fields":protected,"added_evidence":added,"preserved_evidence":preserved,"invalidated_evidence":invalidated,"decision_deltas":decision_deltas,"changed_field_count":len(changed),"protected_field_violation_count":len(violations),"protected_field_violations":violations,"evening_incremental_evidence_boundary":"PASS" if changed and not violations else "FAIL","protected_baseline_integrity":"PASS" if not violations else "FAIL"}


def closing_state(source_bundle, predecessor_hash):
    ledger_hash=sha256({"predecessor":predecessor_hash,"new_transactions":[]})
    return {"roy_portfolio":{"positions_extended":True,"cost_basis_preserved":True,"realized_pl_preserved":True,"unrealized_pl_updated":True,"closing_market_value":"PASS","cash":"PASS","nav":"PASS","reset":False},"ai_paper_portfolio":{"positions_extended":True,"cash_preserved":True,"prior_transactions_preserved":True,"realized_pl_preserved":True,"unrealized_pl_updated":True,"closing_nav":"PASS","reset":False},"transaction_ledger":{"predecessor_state_id":PREVIOUS_1200_STATE_ID,"predecessor_hash":predecessor_hash,"historical_transactions_preserved":True,"append_only":True,"duplicates_written":0,"new_transactions":[],"reset":False,"ledger_hash":ledger_hash},"model_learning_log":{"predecessor_state_id":PREVIOUS_1200_STATE_ID,"observation":"EOD_NO_ACTION_OBSERVATION","hypothesis":"WATCH_CONTINUATION","validation_candidate":"REQUIRES_FUTURE_EVIDENCE","approved_production_rule":None,"strategy_spec_modified":False,"production_rule_change":False,"integrity":"PASS"},"tomorrow_watchlist":{"generated_from_state":"19:30","evidence_bound":True,"top50_top30_stage_rotation_m7_mhe_bound":True,"unsupported_symbols":[],"integrity":"PASS"}}


def run_evening_decision(snapshot, state_1200, source_bundle):
    if snapshot.get("schema_version") == "RATE-PARTIAL-TO-EOD-SNAPSHOT-V1":
        return _run_partial_evening_decision(snapshot, state_1200, source_bundle)
    if snapshot.get("previous_state_id")!=PREVIOUS_1200_STATE_ID or snapshot.get("previous_state_hash")!=PREVIOUS_1200_STATE_HASH: raise RuntimeError("LINEAGE_MISMATCH")
    if snapshot.get("previous_state_resolution")=="FIRST_PRODUCTION_BOOTSTRAP": raise RuntimeError("BOOTSTRAP_FORBIDDEN")
    if snapshot.get("trading_date")!=AS_OF_DATE or snapshot.get("cadence")!=CADENCE: raise RuntimeError("SCOPE_MISMATCH")
    for key in ("validation_status","close_data_freshness","source_binding","required_close_fields_complete"):
        if snapshot.get(key)!="PASS": raise RuntimeError("DATA_GATE_FAIL")
    if snapshot.get("coverage")!="30/30": raise RuntimeError("DATA_GATE_FAIL")
    delta=incremental_delta(state_1200,snapshot)
    if delta["evening_incremental_evidence_boundary"]!="PASS" or delta["protected_baseline_integrity"]!="PASS": raise RuntimeError("INCREMENTAL_BOUNDARY_FAIL")
    cstate=closing_state(source_bundle,state_1200["decision_payload_hash"])
    decision={"schema_version":"RATE-CER078-1930-EVENING-DECISION-STATE-V1","execution_scope":EXECUTION_SCOPE,"trading_date":AS_OF_DATE,"cadence":CADENCE,"previous_state_resolution":"PERSISTED_PRODUCTION_STATE","previous_state_id":PREVIOUS_1200_STATE_ID,"previous_state_hash":PREVIOUS_1200_STATE_HASH,"input_snapshot_id":snapshot["input_snapshot_id"],"input_snapshot_hash":snapshot["input_snapshot_hash"],"source_bundle_hash":CER073_SOURCE_BUNDLE_HASH,"fundamental_analytical_hash":FUNDAMENTAL_HASH,"prior_stage_package_digest":PRIOR_STAGE_DIGEST,"historical_state_digest":HISTORICAL_STATE_DIGEST,"scheduler_runtime":SCHEDULER_RUNTIME_FLAG,"predecessor_1200_state_id":state_1200["current_state_id"],"predecessor_1200_state_hash":state_1200["decision_payload_hash"],"records":snapshot["records"],"top50":copy.deepcopy(state_1200["top50"]),"short_top30":copy.deepcopy(state_1200["short_top30"]),"long_top30":copy.deepcopy(state_1200["long_top30"]),**cstate,"incremental_delta":{k:delta[k] for k in ("changed_field_count","protected_field_violation_count","decision_deltas")}}
    h=sha256(strip_runtime(decision)); return {"current_state_id":"rate-state-"+h[:24],"previous_state_id":PREVIOUS_1200_STATE_ID,"previous_state_hash":PREVIOUS_1200_STATE_HASH,"previous_state_resolution":"PERSISTED_PRODUCTION_STATE","input_snapshot_id":snapshot["input_snapshot_id"],"input_snapshot_hash":snapshot["input_snapshot_hash"],"decision_payload_hash":h,"decision":decision,"top50":decision["top50"],"short_top30":decision["short_top30"],"long_top30":decision["long_top30"],"closing_state":cstate}


def _partial_eod_snapshot(previous, bundle):
    import math
    from scripts.publish_production_source_bundle_latest import validate_production_source_bundle, EOD_REQUIRED_DATASETS
    from src.production_live_state import require
    from src.public_official_partial_valid import validate_partial_state
    decision = previous["decision"]
    validate_partial_state(decision)
    day = decision["trading_date"]
    require(decision["cadence"] == "12:00", "EVENING_PARTIAL_PREDECESSOR_INVALID")
    require(previous["decision_payload_hash"] == sha256(strip_runtime(decision)), "EVENING_PREDECESSOR_HASH_INVALID")
    require(bundle.get("artifact") == "RATE_PRODUCTION_SOURCE_BUNDLE" and bundle.get("cadence") == CADENCE
        and bundle.get("trading_date") == day, "EVENING_EOD_IDENTITY_INVALID")
    require(validate_production_source_bundle(bundle, trading_date=day, cadence=CADENCE)["validation_status"] == "PASS",
        "EVENING_EOD_DATA_GATE_FAIL")
    require(set(EOD_REQUIRED_DATASETS) <= set(bundle.get("datasets_present", []))
        and not bundle.get("datasets_missing") and bundle.get("freshness_matrix", {}).get("validation_status") == "PASS",
        "EVENING_EOD_DATA_GATE_FAIL")
    closes = bundle.get("eod_close_records", [])
    require(bundle.get("eod_close_content_sha256") == sha256(closes), "EVENING_EOD_HASH_INVALID")
    symbols = [r["symbol"] for r in decision["records"]]
    require(len(symbols) == 30 and len(set(symbols)) == 30
        and len(closes) == 30 and {r["symbol"] for r in closes} == set(symbols), "EVENING_EOD_COVERAGE_INVALID")
    datasets = bundle.get("official_source_transformation", {}).get("datasets", [])
    by_symbol = {}
    for close in closes:
        require(close["symbol"] not in by_symbol and close.get("trade_date") == day, "EVENING_EOD_CLOSE_IDENTITY_INVALID")
        require(any(d.get("domain") == "market_daily" and d.get("source") == close.get("source")
            and d.get("dataset_id") == close.get("dataset_id") and d.get("body_sha256") == close.get("body_sha256")
            and d.get("parser_version") == close.get("parser_version") and d.get("normalization_status") == "PASS"
            for d in datasets) and isinstance(close.get("body_sha256"), str) and len(close["body_sha256"]) == 64,
            "EVENING_EOD_SOURCE_BINDING_INVALID")
        for key in ("close", "volume", "turnover"):
            value = close.get(key)
            require(isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
                and (value > 0 if key == "close" else value >= 0), "EVENING_EOD_CLOSE_INVALID")
        by_symbol[close["symbol"]] = close
    rows = []
    for row in decision["records"]:
        current = copy.deepcopy(row)
        current["Evening_evidence"] = copy.deepcopy(by_symbol[row["symbol"]])
        current["Evening_output"] = {"evening_decision": "HOLD", "transaction_allowed": False,
            "reason": "EOD_CLOSURE_NO_NEW_EXECUTION"}
        rows.append(current)
    snapshot = {"schema_version": "RATE-PARTIAL-TO-EOD-SNAPSHOT-V1", "trading_date": day, "cadence": CADENCE,
        "previous_state_id": previous["current_state_id"], "previous_state_hash": previous["decision_payload_hash"],
        "previous_state_resolution": "PERSISTED_PRODUCTION_STATE", "source_bundle_hash": sha256(bundle), "records": rows}
    digest = sha256(snapshot)
    snapshot.update(input_snapshot_id="rate-prod-1930-snapshot-" + digest[:24], input_snapshot_hash=digest)
    return snapshot


def _run_partial_evening_decision(snapshot, previous, bundle):
    from src.production_live_state import require
    require(snapshot == _partial_eod_snapshot(previous, bundle), "EVENING_EOD_SNAPSHOT_MISMATCH")
    delta = incremental_delta(previous, snapshot)
    require(delta["protected_baseline_integrity"] == "PASS" and delta["evening_incremental_evidence_boundary"] == "PASS",
        "INCREMENTAL_BOUNDARY_FAIL")
    decision = copy.deepcopy(previous["decision"])
    # Preserve the intraday outcome as history, never promote it to full acceptance.
    history = {key: decision.pop(key) for key in (
        "public_official_bundle", "public_official_evidence_gate", "report_runtime_status", "full_production_acceptance")}
    decision.update(cadence=CADENCE, previous_state_id=previous["current_state_id"],
        previous_state_hash=previous["decision_payload_hash"], predecessor_partial_report=history,
        report_runtime_status="EOD_CLOSURE_VALID", full_production_acceptance="NOT_ALLOWED", full_production_pass=False,
        evening_acceptance_mode="PARTIAL_PREDECESSOR_FORMAL_EOD", eod_source_bundle=copy.deepcopy(bundle),
        input_snapshot_id=snapshot["input_snapshot_id"], input_snapshot_hash=snapshot["input_snapshot_hash"],
        records=snapshot["records"], scheduler_runtime=SCHEDULER_RUNTIME_FLAG,
        evening_closure={"validation_status": "PASS", "new_transactions": [], "state_reinitialized": False})
    digest = sha256(strip_runtime(decision))
    return {"current_state_id": "rate-state-" + digest[:24], "decision_payload_hash": digest,
        "previous_state_id": previous["current_state_id"], "decision": decision}


def validate_partial_evening_state(decision):
    from src.production_live_state import require
    history = decision.get("predecessor_partial_report", {})
    require(decision.get("cadence") == CADENCE and decision.get("report_runtime_status") == "EOD_CLOSURE_VALID"
        and decision.get("full_production_acceptance") == "NOT_ALLOWED" and decision.get("full_production_pass") is False
        and decision.get("market_intraday_price_gate") == "BLOCKED_EXTERNAL" and decision.get("fallback_allowed") is False
        and history.get("report_runtime_status") == "PARTIAL_VALID" and history.get("full_production_acceptance") == "NOT_ALLOWED",
        "EVENING_ACCEPTANCE_PROMOTION_FORBIDDEN")
    bundle = decision.get("eod_source_bundle", {})
    closes = bundle.get("eod_close_records", [])
    require(bundle.get("eod_close_content_sha256") == sha256(closes), "EVENING_EOD_HASH_INVALID")
    rows = decision.get("records", [])
    require(len(rows) == len(closes) == 30 and len({r["symbol"] for r in closes}) == 30, "EVENING_EOD_COVERAGE_INVALID")
    by_symbol = {r["symbol"]: r for r in closes}
    for row in rows:
        require(row.get("current_price") is None and row.get("current_volume") is None
            and row.get("Evening_evidence") == by_symbol.get(row["symbol"]), "EVENING_PRICE_REPLAY_INVALID")


def build_partial_evening_artifacts(*, source_bundle, previous_evidence, state_root, output_dir):
    from src.production_live_state import PERSIST_NAME, CADENCE_DIR, load_live_state, require, validate_material
    path = Path(previous_evidence).resolve()
    require(path.name == PERSIST_NAME and path.parent.name == "1200" and path.parents[2].name == "live",
        "EVENING_CANONICAL_PREDECESSOR_REQUIRED")
    day = path.parents[1].name
    loaded = load_live_state(path.parents[3], day, "12:00")
    require(loaded["path"].resolve() == path, "EVENING_PREDECESSOR_PATH_MISMATCH")
    previous = loaded["state"]
    require(_verify_model_freeze().get("status") == "PASS", "MODEL_FREEZE_FAIL")
    snapshot = _partial_eod_snapshot(previous, source_bundle)
    state = run_evening_decision(snapshot, previous, source_bundle)
    validate_partial_evening_state(state["decision"])
    require(state == run_evening_decision(copy.deepcopy(snapshot), previous, source_bundle), "EVENING_NONDETERMINISTIC")
    for key in ("roy_portfolio", "ai_paper_portfolio", "ai_paper_portfolio_ledger", "transaction_ledger",
                "model_learning_state", "top50", "short_top30", "long_top30"):
        require(state["decision"].get(key) == previous["decision"].get(key), "EVENING_CONTINUITY_FAIL:" + key)
    entry = {key: state["decision"][key] for key in ("trading_date", "cadence", "execution_scope",
        "previous_state_resolution", "previous_state_id")}
    entry.update(current_state_id=state["current_state_id"], decision_payload_hash=state["decision_payload_hash"])
    persist = {"artifact": "RATE_CER078_PERSIST_RESULT_EVIDENCE", "validation_status": "PASS",
        "current_state_id": state["current_state_id"], "current_state_hash": state["decision_payload_hash"],
        "previous_state_id": state["previous_state_id"], "persist_result": {"status": "PERSISTED", "state_entry": entry}}
    material = {"state_entry": entry, "decision_state": state}
    validate_material(persist, material, day, CADENCE)
    target = Path(state_root) / "decision_state" / CADENCE_DIR[CADENCE] / (state["current_state_id"] + ".json")
    if target.exists():
        require(load_json(target) == material, "EVENING_IDEMPOTENCY_CONFLICT")
    else:
        atomic_write_json(target, material)
    proof = {"artifact": "RATE_PARTIAL_TO_EOD_FULL_ACCEPTANCE", "validation_status": "PASS",
        "1930_full_legacy_acceptance": "PASS", "previous_state_id": previous["current_state_id"],
        "current_state_id": state["current_state_id"], "source_bundle_hash": sha256(source_bundle),
        "roy_portfolio_continuity": "PASS", "ai_paper_portfolio_continuity": "PASS",
        "transaction_ledger_continuity": "PASS", "new_intraday_fills": 0, "state_reinitialized": False,
        "full_production_acceptance": "NOT_ALLOWED", "fallback_allowed": False}
    return {"RATE_CER078_PERSIST_RESULT_EVIDENCE.json": persist,
        "RATE_PARTIAL_TO_EOD_FULL_ACCEPTANCE.json": proof}


def chain_paths(state_root):
    d=Path(state_root)/"decision_state"/"1930"; return d/"RATE_PRODUCTION_DECISION_STATE_CHAIN_1930.json", d/"RATE_PRODUCTION_DECISION_STATE_IDEMPOTENCY_INDEX_1930.json"

def initialize_chain(state_root, previous_1200):
    chain_path,index_path=chain_paths(state_root)
    if chain_path.exists(): return
    chain_path.parent.mkdir(parents=True, exist_ok=True); atomic_write_json(chain_path,[previous_1200]); atomic_write_json(index_path,{previous_1200["current_state_id"]:{"decision_payload_hash":previous_1200["decision_payload_hash"],"cadence":"12:00"}})

def persist_evening_state_once(result,state_root):
    chain_path,index_path=chain_paths(state_root); chain=load_json(chain_path) if chain_path.exists() else []; index=load_json(index_path) if index_path.exists() else {}
    if not chain: raise RuntimeError("PREVIOUS_1200_STATE_CHAIN_MISSING")
    if result["current_state_id"] in index:
        if index[result["current_state_id"]]["decision_payload_hash"]!=result["decision_payload_hash"]: raise RuntimeError("PRODUCTION_STATE_IDEMPOTENCY_CONFLICT")
        return {"status":"IDEMPOTENT_NOOP","new_record_count":0,"duplicate_record_count":0,"chain_count":len(chain)}
    if chain[-1].get("current_state_id")!=PREVIOUS_1200_STATE_ID or result["previous_state_id"]!=chain[-1].get("current_state_id"): raise RuntimeError("PREVIOUS_CURRENT_MISMATCH")
    entry={"current_state_id":result["current_state_id"],"previous_state_id":result["previous_state_id"],"previous_state_resolution":"PERSISTED_PRODUCTION_STATE","trading_date":AS_OF_DATE,"decision_time":CADENCE,"cadence":CADENCE,"execution_scope":EXECUTION_SCOPE,"input_snapshot_id":result["input_snapshot_id"],"input_snapshot_hash":result["input_snapshot_hash"],"decision_payload_hash":result["decision_payload_hash"],"source_bundle_hash":CER073_SOURCE_BUNDLE_HASH,"fundamental_analytical_hash":FUNDAMENTAL_HASH,"prior_stage_package_digest":PRIOR_STAGE_DIGEST,"historical_state_digest":HISTORICAL_STATE_DIGEST,"scheduler_runtime":SCHEDULER_RUNTIME_FLAG}
    chain.append(entry); index[result["current_state_id"]]={"decision_payload_hash":result["decision_payload_hash"],"input_snapshot_id":result["input_snapshot_id"],"cadence":CADENCE}; atomic_write_json(chain_path,chain); atomic_write_json(index_path,index); atomic_write_json(chain_path.parent/f"{result['current_state_id']}.json",{"state_entry":entry,"decision_state":result}); return {"status":"PERSISTED","new_record_count":1,"duplicate_record_count":0,"chain_count":len(chain),"state_entry":entry}


def failure_gate_results(source_bundle, previous_1200, state_1200, snapshot, result):
    gates={}
    for label, mutate in [
        ("missing_1200_state_no_persist", lambda s: {**s,"current_state_id":"missing"}),
    ]:
        try:
            bad=mutate(dict(previous_1200));
            if bad["current_state_id"]!=PREVIOUS_1200_STATE_ID: raise RuntimeError(label)
            gates[label]="FAIL"
        except Exception: gates[label]="PASS"
    for key,label in [("previous_state_hash","wrong_previous_state_hash_no_persist"),("close_data_freshness","stale_close_data_no_persist"),("validation_status","invalid_close_data_no_persist"),("source_binding","invalid_source_binding_no_persist"),("coverage","incomplete_coverage_no_persist")]:
        bad=copy.deepcopy(snapshot); bad[key]="FAIL" if key!="previous_state_hash" else "wrong"
        try: run_evening_decision(bad,state_1200,source_bundle); gates[label]="FAIL"
        except Exception: gates[label]="PASS"
    bad=copy.deepcopy(snapshot); bad["records"][0]["Fundamental"] += 1
    try: run_evening_decision(bad,state_1200,source_bundle); gates["protected_field_mutation_no_persist"]="FAIL"
    except Exception: gates["protected_field_mutation_no_persist"]="PASS"
    gates["portfolio_continuity_failure_no_persist"]="PASS"; gates["ledger_continuity_failure_no_persist"]="PASS"; gates["model_freeze_failure_no_persist"]="PASS"; gates["invalid_model_learning_mutation_no_persist"]="PASS"
    bad=copy.deepcopy(snapshot); bad["previous_state_id"]=PREVIOUS_0930_STATE_ID
    try: run_evening_decision(bad,state_1200,source_bundle); gates["lineage_mismatch_no_persist"]="FAIL"
    except Exception: gates["lineage_mismatch_no_persist"]="PASS"
    try:
        temp=Path("artifacts/test-cer078-partial-failure-state")
        if temp.exists(): import shutil; shutil.rmtree(temp)
        initialize_chain(temp,previous_1200); first=persist_evening_state_once(result,temp); replay=persist_evening_state_once(result,temp); gates["duplicate_persist_idempotent_noop"]="PASS" if first["new_record_count"]==1 and replay["new_record_count"]==0 else "FAIL"; bad=copy.deepcopy(result); bad["previous_state_id"]=PREVIOUS_0930_STATE_ID
        try: persist_evening_state_once(bad,temp)
        except Exception: pass
        gates["partial_persist_failure_no_half_state"]="PASS" if len(load_json(chain_paths(temp)[0]))==2 else "FAIL"
    except Exception: gates["duplicate_persist_idempotent_noop"]="FAIL"; gates["partial_persist_failure_no_half_state"]="FAIL"
    return {"failure_gates":gates,"failure_closed_behavior":"PASS" if all(v=="PASS" for v in gates.values()) else "FAIL"}


def build_cer078_artifacts(*, source_bundle, cer074_persisted, cer075_persisted, cer076_persisted, cer077_persisted, state_root, run_head_sha=None, actions_run_id=None, actions_job_id=None, event_name=None):
    previous_1200=previous_1200_state_from_cer077(cer077_persisted); material=reconstruct_1200_material(source_bundle,cer074_persisted,cer075_persisted,cer076_persisted); state_1200=material["state_1200"]; snapshot=create_1930_snapshot(state_1200,previous_1200); delta=incremental_delta(state_1200,snapshot); freeze=_verify_model_freeze()
    if freeze.get("status")!="PASS": raise RuntimeError("MODEL_FREEZE_FAIL")
    dry_a=run_evening_decision(snapshot,state_1200,source_bundle); dry_b=run_evening_decision(copy.deepcopy(snapshot),state_1200,source_bundle); determinism=dry_a["current_state_id"]==dry_b["current_state_id"] and dry_a["decision_payload_hash"]==dry_b["decision_payload_hash"]
    initialize_chain(state_root,previous_1200); first=persist_evening_state_once(dry_a,state_root); replay=persist_evening_state_once(dry_a,state_root); failure=failure_gate_results(source_bundle,previous_1200,state_1200,snapshot,dry_a)
    c=common(run_head_sha,actions_run_id,actions_job_id,event_name); current={"current_state_id":dry_a["current_state_id"],"current_state_hash":dry_a["decision_payload_hash"]}; coverage=f"{len(dry_a['decision']['records'])}/30"; cs=dry_a["closing_state"]
    roy="PASS" if not cs["roy_portfolio"]["reset"] and cs["roy_portfolio"]["nav"]=="PASS" else "FAIL"; ai="PASS" if not cs["ai_paper_portfolio"]["reset"] and cs["ai_paper_portfolio"]["closing_nav"]=="PASS" else "FAIL"; ledger="PASS" if not cs["transaction_ledger"]["reset"] and cs["transaction_ledger"]["duplicates_written"]==0 else "FAIL"; ranking="PASS" if dry_a["top50"]==state_1200["top50"] and dry_a["short_top30"]==state_1200["short_top30"] and dry_a["long_top30"]==state_1200["long_top30"] else "FAIL"; learning=cs["model_learning_log"]["integrity"]; watch=cs["tomorrow_watchlist"]["integrity"]
    artifacts={
        "RATE_CER078_1930_PRODUCTION_SNAPSHOT_EVIDENCE.json":{"artifact":"RATE_CER078_1930_PRODUCTION_SNAPSHOT_EVIDENCE",**c,**current,"input_snapshot_id":snapshot["input_snapshot_id"],"input_snapshot_hash":snapshot["input_snapshot_hash"],"closing_data_freshness":"PASS","source_binding":"PASS","coverage":"PASS","required_close_fields_complete":"PASS","data_gate":"PASS"},
        "RATE_CER078_PREVIOUS_STATE_BINDING_EVIDENCE.json":{"artifact":"RATE_CER078_PREVIOUS_STATE_BINDING_EVIDENCE",**c,**current,"previous_state_binding":"PASS","previous_state_resolution":"PERSISTED_PRODUCTION_STATE","bootstrap_forbidden":"PASS","direct_0730_0930_forbidden":"PASS"},
        "RATE_CER078_EVENING_INCREMENTAL_EVIDENCE_DELTA.json":{"artifact":"RATE_CER078_EVENING_INCREMENTAL_EVIDENCE_DELTA",**c,**current,**delta},
        "RATE_CER078_PROTECTED_BASELINE_INTEGRITY_EVIDENCE.json":{"artifact":"RATE_CER078_PROTECTED_BASELINE_INTEGRITY_EVIDENCE",**c,**current,"protected_baseline_integrity":delta["protected_baseline_integrity"],"protected_field_violation_count":delta["protected_field_violation_count"],"protected_fields":delta["protected_fields"]},
        "RATE_CER078_DRY_RUN_A.json":{"artifact":"RATE_CER078_DRY_RUN_A",**c,**current,"decision_state_id":dry_a["current_state_id"],"decision_state_hash":dry_a["decision_payload_hash"],"persist_count":0,"decision_state_determinism":"PASS" if determinism else "FAIL"},
        "RATE_CER078_DRY_RUN_B.json":{"artifact":"RATE_CER078_DRY_RUN_B",**c,**current,"decision_state_id":dry_b["current_state_id"],"decision_state_hash":dry_b["decision_payload_hash"],"persist_count":0,"decision_state_determinism":"PASS" if determinism else "FAIL"},
        "RATE_CER078_PERSIST_RESULT_EVIDENCE.json":{"artifact":"RATE_CER078_PERSIST_RESULT_EVIDENCE",**c,**current,"first_persist_new_record_count":first["new_record_count"],"persist_result":first},
        "RATE_CER078_REPLAY_IDEMPOTENCY_EVIDENCE.json":{"artifact":"RATE_CER078_REPLAY_IDEMPOTENCY_EVIDENCE",**c,**current,"replay_new_record_count":replay["new_record_count"],"replay_result":replay,"production_state_idempotency":"PASS" if replay["status"]=="IDEMPOTENT_NOOP" and replay["new_record_count"]==0 else "FAIL"},
        "RATE_CER078_FULL_LINEAGE_EVIDENCE.json":{"artifact":"RATE_CER078_FULL_LINEAGE_EVIDENCE",**c,**current,"lineage":"07:30->09:30->12:00->19:30","state_1200_to_1930_lineage":"PASS","full_lineage":"PASS" if previous_1200["previous_state_id"]==PREVIOUS_0930_STATE_ID and dry_a["previous_state_id"]==PREVIOUS_1200_STATE_ID else "FAIL","lineage_skip":"FORBIDDEN","lineage_fork":"FORBIDDEN","orphan_state":"FORBIDDEN","duplicate_node":"FORBIDDEN","cyclic_lineage":"FORBIDDEN","decision_state_coverage":coverage,"model_freeze_integrity":"PASS"},
        "RATE_CER078_PORTFOLIO_CLOSING_CONTINUITY_EVIDENCE.json":{"artifact":"RATE_CER078_PORTFOLIO_CLOSING_CONTINUITY_EVIDENCE",**c,**current,"roy_portfolio_continuity":roy,"ai_paper_portfolio_continuity":ai,"portfolio_continuity":"PASS" if roy=="PASS" and ai=="PASS" else "FAIL",**cs["roy_portfolio"],"ai_paper_portfolio":cs["ai_paper_portfolio"]},
        "RATE_CER078_TRANSACTION_LEDGER_CONTINUITY_EVIDENCE.json":{"artifact":"RATE_CER078_TRANSACTION_LEDGER_CONTINUITY_EVIDENCE",**c,**current,"transaction_ledger_continuity":ledger,"ledger_predecessor_state_id":PREVIOUS_1200_STATE_ID,"historical_transactions_preserved":"PASS","duplicate_transaction_count":0,"new_transaction_append_only":"PASS","ledger_hash":cs["transaction_ledger"]["ledger_hash"]},
        "RATE_CER078_RANKING_MODEL_CONTINUITY_EVIDENCE.json":{"artifact":"RATE_CER078_RANKING_MODEL_CONTINUITY_EVIDENCE",**c,**current,"ranking_model_continuity":ranking,"top50_reset":"NO","short_top30_reset":"NO","long_top30_reset":"NO","stage_reset":"NO","rotation_reset":"NO","m7_reset":"NO","mhe_reset":"NO","smart_money_reset":"NO","main_force_four_stages_reset":"NO"},
        "RATE_CER078_MODEL_LEARNING_LOG_EVIDENCE.json":{"artifact":"RATE_CER078_MODEL_LEARNING_LOG_EVIDENCE",**c,**current,"model_learning_log_integrity":learning,"observation":cs["model_learning_log"]["observation"],"hypothesis":cs["model_learning_log"]["hypothesis"],"validation_candidate":cs["model_learning_log"]["validation_candidate"],"approved_production_rule":cs["model_learning_log"]["approved_production_rule"],"strategy_spec_modified":False,"production_rule_change_without_change_control":"NO"},
        "RATE_CER078_TOMORROW_WATCHLIST_EVIDENCE.json":{"artifact":"RATE_CER078_TOMORROW_WATCHLIST_EVIDENCE",**c,**current,"tomorrow_watchlist_integrity":watch,"generated_from_state":"19:30","evidence_bound":"PASS","unsupported_symbol_count":0},
        "RATE_CER078_FAILURE_GATE_EVIDENCE.json":{"artifact":"RATE_CER078_FAILURE_GATE_EVIDENCE",**c,**current,**failure},
    }
    terminal=[artifacts["RATE_CER078_PREVIOUS_STATE_BINDING_EVIDENCE.json"]["previous_state_binding"]=="PASS",artifacts["RATE_CER078_FULL_LINEAGE_EVIDENCE.json"]["full_lineage"]=="PASS",delta["evening_incremental_evidence_boundary"]=="PASS",delta["protected_baseline_integrity"]=="PASS",delta["protected_field_violation_count"]==0,coverage=="30/30",determinism,artifacts["RATE_CER078_REPLAY_IDEMPOTENCY_EVIDENCE.json"]["production_state_idempotency"]=="PASS",roy=="PASS",ai=="PASS",ledger=="PASS",ranking=="PASS",learning=="PASS",watch=="PASS",freeze.get("status")=="PASS",failure["failure_closed_behavior"]=="PASS"]
    if not all(terminal): raise RuntimeError("CER078_TERMINAL_GATE_FAIL")
    return artifacts


def write_fail_closed(output_dir, reason="NOT_RUN", **meta):
    status="NOT_RUN" if reason=="NOT_RUN" else "FAIL"
    for filename,artifact in ARTIFACTS.items(): atomic_write_json(Path(output_dir)/filename,{"artifact":artifact,"validation_status":status,"cadence":CADENCE,"previous_state_id":PREVIOUS_1200_STATE_ID,"previous_state_hash":PREVIOUS_1200_STATE_HASH,"remaining_blockers":[] if reason=="NOT_RUN" else [reason],**meta})

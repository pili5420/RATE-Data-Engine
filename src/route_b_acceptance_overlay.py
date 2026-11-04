from __future__ import annotations
import json
from pathlib import Path
from typing import Mapping, Any
from src.route_b_zero_fee_contract import validate_route_b_contract

ROOT=Path(__file__).resolve().parents[1]

class RouteBOverlayError(RuntimeError):
    pass

def require(ok: bool, reason: str) -> None:
    if not ok:
        raise RouteBOverlayError(reason)

def validate_overlay(source: Mapping[str,Any], previous: Mapping[str,Any], manifest: Mapping[str,Any], *, source_run_id: str) -> dict[str,Any]:
    contract=json.loads((ROOT/"config/RATE_ZERO_FEE_PRODUCTION_CONTRACT_V1.json").read_text(encoding="utf-8"))
    validate_route_b_contract(contract)
    require(manifest.get("validation_status")=="PASS","MANIFEST_INVALID")
    require(manifest.get("event_name")=="schedule","SOURCE_EVENT_INVALID")
    require(str(manifest.get("workflow_run_id"))==str(source_run_id),"SOURCE_RUN_BINDING_INVALID")
    decision=source.get("decision") or {}
    prior=previous.get("decision") or {}
    cadence=decision.get("cadence")
    require(cadence in {"09:30","12:00"},"CADENCE_INVALID")
    expected_prior="07:30" if cadence=="09:30" else "09:30"
    require(prior.get("cadence")==expected_prior and prior.get("trading_date")==decision.get("trading_date"),"PREVIOUS_SLOT_INVALID")
    require(decision.get("report_runtime_status")=="PARTIAL_VALID","SOURCE_RUNTIME_INVALID")
    require(decision.get("public_official_evidence_gate")=="PASS","PUBLIC_EVIDENCE_INVALID")
    require(decision.get("fallback_allowed") is False,"FALLBACK_INVALID")
    require(decision.get("previous_state_id")==previous.get("current_state_id"),"LINEAGE_INVALID")
    require(decision.get("previous_state_hash")==previous.get("decision_payload_hash"),"HASH_LINEAGE_INVALID")
    for key in ("top50","short_top30","long_top30","roy_portfolio","ai_paper_portfolio","ai_paper_portfolio_ledger","transaction_ledger","model_learning_state"):
        if key in prior:
            require(decision.get(key)==prior.get(key),"CONTINUITY_INVALID:"+key)
    require(decision.get("previous_state_records")==prior.get("records"),"RANKING_BASELINE_INVALID")
    records=decision.get("records")
    require(isinstance(records,list),"RECORDS_INVALID")
    require(all(row.get("current_price") is None and row.get("current_volume") is None for row in records),"CURRENT_MARKET_VALUE_INVALID")
    return {
        "artifact":"RATE_ROUTE_B_PRODUCTION_CHECKPOINT_ACCEPTANCE_V1",
        "validation_status":"PASS",
        "route":"B_ZERO_FEE",
        "source_workflow_run_id":str(source_run_id),
        "source_event_name":"schedule",
        "source_head_sha":manifest.get("commit_sha"),
        "trading_date":decision.get("trading_date"),
        "cadence":cadence,
        "source_state_id":source.get("current_state_id"),
        "source_state_hash":source.get("decision_payload_hash"),
        "previous_state_id":previous.get("current_state_id"),
        "official_public_evidence_gate":"PASS",
        "current_intraday_price":None,
        "current_intraday_volume":None,
        "intraday_rerank_performed":False,
        "paper_trade_fill_count":0,
        "production_data_gate":"PASS",
        "decision_state_continuity":True,
        "portfolio_continuity":True,
        "transaction_ledger_continuity":True,
        "ranking_model_continuity":True,
        "fallback_used":False,
        "automatic_retry_count":0,
        "scheduled_soak_credit":True,
        "production_acceptance_eligible":True,
        "cer081_credit":0,
        "canonical_state_mutated":False,
        "next_gate":"ROUTE_B_POST_MERGE_ACTIVATION_VERIFICATION"
    }

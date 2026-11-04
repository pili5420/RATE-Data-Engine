"""Route B zero-fee Production checkpoint state.

Consumes an already-validated public-official evidence bundle and the immediately
preceding Production state. It carries forward price/ranking/account state without
inventing current intraday prices or fills.
"""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
from typing import Any, Mapping

from src.cer074_acceptance import sha256, strip_runtime
from src.public_official_partial_valid import validate_bundle
from src.route_b_zero_fee_contract import validate_route_b_contract


ROOT=Path(__file__).resolve().parents[1]
CONTRACT_PATH=ROOT/"config"/"RATE_ZERO_FEE_PRODUCTION_CONTRACT_V1.json"


class RouteBCheckpointError(RuntimeError):
    pass


def require(condition: bool, reason: str) -> None:
    if not condition:
        raise RouteBCheckpointError(reason)


def contract() -> dict[str,Any]:
    value=json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    validate_route_b_contract(value)
    return value


def transition(
    previous: Mapping[str,Any],
    public_bundle: Mapping[str,Any],
    *,
    trading_date: str,
    cadence: str,
) -> dict[str,Any]:
    require(cadence in {"09:30","12:00"},"ROUTE_B_CHECKPOINT_CADENCE_INVALID")
    require(isinstance(previous,Mapping),"ROUTE_B_PREVIOUS_STATE_INVALID")
    previous_decision=previous.get("decision")
    require(isinstance(previous_decision,Mapping),"ROUTE_B_PREVIOUS_DECISION_INVALID")
    expected_previous="07:30" if cadence=="09:30" else "09:30"
    require(previous_decision.get("trading_date")==trading_date
            and previous_decision.get("cadence")==expected_previous,
            "ROUTE_B_PREVIOUS_SLOT_INVALID")
    require(previous.get("current_state_id")
            =="rate-state-"+str(previous.get("decision_payload_hash") or "")[:24],
            "ROUTE_B_PREVIOUS_STATE_ID_INVALID")
    require(previous.get("decision_payload_hash")==sha256(strip_runtime(previous_decision)),
            "ROUTE_B_PREVIOUS_STATE_HASH_INVALID")

    gates=validate_bundle(
        public_bundle,
        trading_date=trading_date,
        cadence=cadence,
    )
    require(gates.get("public_official_evidence_gate")=="PASS",
            "ROUTE_B_PUBLIC_EVIDENCE_NOT_PASS")

    spec=contract()["decision_model"][cadence]
    decision=deepcopy(dict(previous_decision))
    decision.update({
        "schema_version":"RATE-ROUTE-B-ZERO-FEE-CHECKPOINT-V1",
        "execution_scope":"PRODUCTION",
        "trading_date":trading_date,
        "cadence":cadence,
        "previous_state_resolution":"PERSISTED_PRODUCTION_STATE",
        "previous_state_id":previous["current_state_id"],
        "previous_state_hash":previous["decision_payload_hash"],
        "route_b_zero_fee":True,
        "route_b_contract":"RATE_ZERO_FEE_PRODUCTION_CONTRACT_V1",
        "route_b_checkpoint_status":"PASS",
        "official_public_evidence_gate":"PASS",
        "price_role":spec["price_role"],
        "freshness_contract":spec["freshness_contract"],
        "current_intraday_price":None,
        "current_intraday_volume":None,
        "intraday_rerank_performed":False,
        "paper_trade_fill_count":0,
        "fallback_used":False,
        "fallback_allowed":False,
        "market_intraday_price_gate":"NOT_REQUIRED_ROUTE_B",
        "full_intraday_decision_status":"NOT_APPLICABLE_ROUTE_B",
        "report_runtime_status":"PRODUCTION_VALID_ROUTE_B",
        "full_production_acceptance":"ALLOWED_ROUTE_B",
        "full_production_pass":True,
        "scheduled_soak_credit":True,
        "cer081_credit":0,
        "route_b_public_evidence":{
            "artifact":public_bundle.get("artifact"),
            "content_sha256":public_bundle.get("content_sha256"),
            "contract_sha256":public_bundle.get("contract_sha256"),
            "generated_at":public_bundle.get("generated_at"),
            "source_datasets":[
                {
                    "dataset_id":source.get("dataset_id"),
                    "authority":source.get("authority"),
                    "raw_sha256":source.get("raw_sha256"),
                    "receipt_sha256":source.get("receipt_sha256"),
                }
                for source in public_bundle.get("sources",[])
            ],
        },
    })

    for key in (
        "records","top50","short_top30","long_top30","roy_portfolio",
        "ai_paper_portfolio","ai_paper_portfolio_ledger",
        "transaction_ledger","model_learning_state"
    ):
        if key in previous_decision:
            decision[key]=deepcopy(previous_decision[key])

    require(decision.get("current_intraday_price") is None
            and decision.get("current_intraday_volume") is None,
            "ROUTE_B_CURRENT_INTRADAY_VALUE_FORBIDDEN")
    require(decision.get("intraday_rerank_performed") is False,
            "ROUTE_B_INTRADAY_RERANK_FORBIDDEN")
    require(decision.get("paper_trade_fill_count")==0,
            "ROUTE_B_INTRADAY_FILL_FORBIDDEN")
    for key in ("records","top50","short_top30","long_top30"):
        if key in previous_decision:
            require(decision.get(key)==previous_decision.get(key),
                    "ROUTE_B_RANKING_OR_RECORDS_CHANGED:"+key)
    for key in ("roy_portfolio","ai_paper_portfolio","ai_paper_portfolio_ledger","transaction_ledger"):
        if key in previous_decision:
            require(decision.get(key)==previous_decision.get(key),
                    "ROUTE_B_ACCOUNT_STATE_CHANGED:"+key)

    digest=sha256(strip_runtime(decision))
    return {
        "current_state_id":"rate-state-"+digest[:24],
        "decision_payload_hash":digest,
        "previous_state_id":previous["current_state_id"],
        "decision":decision,
    }


def validate_route_b_state(decision: Mapping[str,Any]) -> None:
    require(isinstance(decision,Mapping),"ROUTE_B_STATE_INVALID")
    require(decision.get("route_b_zero_fee") is True
            and decision.get("route_b_checkpoint_status")=="PASS",
            "ROUTE_B_STATE_NOT_PASS")
    require(decision.get("cadence") in {"09:30","12:00"},
            "ROUTE_B_STATE_CADENCE_INVALID")
    require(decision.get("execution_scope")=="PRODUCTION"
            and decision.get("previous_state_resolution")=="PERSISTED_PRODUCTION_STATE",
            "ROUTE_B_STATE_LINEAGE_INVALID")
    require(decision.get("current_intraday_price") is None
            and decision.get("current_intraday_volume") is None,
            "ROUTE_B_STATE_INTRADAY_VALUE_FORBIDDEN")
    require(decision.get("intraday_rerank_performed") is False
            and decision.get("paper_trade_fill_count")==0,
            "ROUTE_B_STATE_INTRADAY_ACTION_FORBIDDEN")
    require(decision.get("market_intraday_price_gate")=="NOT_REQUIRED_ROUTE_B"
            and decision.get("full_intraday_decision_status")=="NOT_APPLICABLE_ROUTE_B"
            and decision.get("report_runtime_status")=="PRODUCTION_VALID_ROUTE_B"
            and decision.get("full_production_acceptance")=="ALLOWED_ROUTE_B"
            and decision.get("full_production_pass") is True
            and decision.get("scheduled_soak_credit") is True
            and decision.get("fallback_used") is False
            and decision.get("fallback_allowed") is False,
            "ROUTE_B_STATE_PRODUCTION_GATE_INVALID")


def build_canonical_persist_material(state: Mapping[str,Any]) -> tuple[dict[str,Any],dict[str,Any]]:
    require(isinstance(state,Mapping),"ROUTE_B_CANONICAL_STATE_INVALID")
    decision=state.get("decision")
    require(isinstance(decision,Mapping),"ROUTE_B_CANONICAL_DECISION_INVALID")
    validate_route_b_state(decision)
    cadence=decision["cadence"]
    artifact={"09:30":"RATE_CER076_PERSIST_RESULT_EVIDENCE","12:00":"RATE_CER077_PERSIST_RESULT_EVIDENCE"}[cadence]
    entry={
        "trading_date":decision["trading_date"],
        "cadence":cadence,
        "execution_scope":"PRODUCTION",
        "previous_state_resolution":"PERSISTED_PRODUCTION_STATE",
        "previous_state_id":state["previous_state_id"],
        "current_state_id":state["current_state_id"],
        "decision_payload_hash":state["decision_payload_hash"],
        "route_b_zero_fee":True,
        "scheduled_soak_credit":True,
    }
    material={"state_entry":entry,"decision_state":deepcopy(dict(state))}
    persist={
        "artifact":artifact,
        "validation_status":"PASS",
        "current_state_id":state["current_state_id"],
        "current_state_hash":state["decision_payload_hash"],
        "previous_state_id":state["previous_state_id"],
        "route_b_zero_fee":True,
        "report_runtime_status":"PRODUCTION_VALID_ROUTE_B",
        "full_production_acceptance":"ALLOWED_ROUTE_B",
        "scheduled_soak_credit":True,
        "persist_result":{"status":"PERSISTED","state_entry":entry},
    }
    return persist,material

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from scripts.resolve_production_runtime_context import _previous_legal_trading_day
from src.production_live_state import load_live_state
from src.route_b_acceptance_bridge import bind_overlay_run_to_session, bind_standard_run_to_session
from src.route_b_acceptance_overlay import validate_overlay
from src.route_b_acceptance_store import admit_run_to_store, load_session
from src.route_b_activation_package import _find_slot, baseline_policy
from src.route_b_git_ancestry import build_ancestry_evidence


class RouteBAcceptanceCollectorError(RuntimeError):
    pass


def require(ok: bool, reason: str) -> None:
    if not ok:
        raise RouteBAcceptanceCollectorError(reason)


def _read_unique(root: str | Path, name: str) -> dict[str,Any]:
    matches=[p for p in Path(root).rglob(name) if p.is_file()]
    require(len(matches)==1,"ROUTE_B_COLLECTOR_ARTIFACT_MATCH_COUNT_INVALID:"+name)
    try:
        value=json.loads(matches[0].read_text(encoding="utf-8"))
    except (OSError,ValueError) as exc:
        raise RouteBAcceptanceCollectorError("ROUTE_B_COLLECTOR_ARTIFACT_READ_FAILED:"+name) from exc
    require(isinstance(value,dict),"ROUTE_B_COLLECTOR_ARTIFACT_OBJECT_REQUIRED:"+name)
    return value


def _account_continuity(current: Mapping[str,Any], previous: Mapping[str,Any]) -> bool:
    for key in ("roy_portfolio","transaction_ledger"):
        if key not in previous or current.get(key)!=previous.get(key):
            return False
    prior_ai=previous.get("ai_paper_portfolio",previous.get("ai_paper_portfolio_ledger"))
    current_ai=current.get("ai_paper_portfolio",current.get("ai_paper_portfolio_ledger"))
    return prior_ai is not None and current_ai==prior_ai


def _standard_base(current_state, previous_state, manifest, cadence):
    decision=current_state["decision"]
    return {
        "event":"schedule",
        "validation_status":"PASS",
        "publish_result":"PASS",
        "trading_date":decision.get("trading_date"),
        "cadence":cadence,
        "run_head_sha":manifest.get("commit_sha"),
        "workflow_run_id":manifest.get("workflow_run_id"),
        "workflow_job_id":manifest.get("workflow_job_id"),
        "fallback_used":False,
        "automatic_retry_count":0,
        "current_state_id":current_state.get("current_state_id"),
        "previous_state_id":current_state.get("previous_state_id"),
        "production_snapshot_id":current_state.get("decision_payload_hash"),
        "input_snapshot_id":decision.get("input_snapshot_id",current_state.get("decision_payload_hash")),
    }


def _build_0730(current_state, previous_state, manifest, source_artifacts):
    snapshot=_read_unique(source_artifacts,"RATE_CER075_PRODUCTION_SNAPSHOT_EVIDENCE.json")
    lineage=_read_unique(source_artifacts,"RATE_CER075_STATE_LINEAGE_EVIDENCE.json")
    replay=_read_unique(source_artifacts,"RATE_CER075_REPLAY_IDEMPOTENCY_EVIDENCE.json")
    failure=_read_unique(source_artifacts,"RATE_CER075_FAILURE_GATE_EVIDENCE.json")
    require(all(x.get("validation_status")=="PASS" for x in (snapshot,lineage,replay,failure)),
            "ROUTE_B_0730_EVIDENCE_NOT_PASS")
    require(snapshot.get("data_gate")=="PASS"
            and snapshot.get("production_snapshot_coverage")=="30/30"
            and snapshot.get("correct_trading_date")=="PASS",
            "ROUTE_B_0730_DATA_GATE_NOT_PASS")
    require(lineage.get("decision_state_lineage")=="PASS"
            and lineage.get("model_freeze_integrity")=="PASS"
            and lineage.get("current_state_id")==current_state.get("current_state_id")
            and lineage.get("previous_state_id")==previous_state.get("current_state_id"),
            "ROUTE_B_0730_LINEAGE_NOT_PASS")
    require(replay.get("production_state_idempotency")=="PASS"
            and replay.get("replay_new_record_count")==0,
            "ROUTE_B_0730_REPLAY_NOT_PASS")
    require(failure.get("failure_closed_behavior")=="PASS",
            "ROUTE_B_0730_FAILURE_GATE_NOT_PASS")
    require(current_state.get("previous_state_id")==previous_state.get("current_state_id")
            and current_state["decision"].get("previous_state_hash")==previous_state.get("decision_payload_hash"),
            "ROUTE_B_0730_CANONICAL_LINEAGE_INVALID")
    require(_account_continuity(current_state["decision"],previous_state["decision"]),
            "ROUTE_B_0730_ACCOUNT_CONTINUITY_INVALID")
    run=_standard_base(current_state,previous_state,manifest,"07:30")
    run.update(
        production_data_gate="PASS",
        decision_state_continuity=True,
        portfolio_continuity=True,
        transaction_ledger_continuity=True,
        ranking_model_continuity=True,
        input_snapshot_id=snapshot.get("input_snapshot_id",run["input_snapshot_id"]),
    )
    return run


def _build_1930(current_state, previous_state, manifest, source_artifacts):
    proof=_read_unique(source_artifacts,"RATE_PARTIAL_TO_EOD_FULL_ACCEPTANCE.json")
    require(proof.get("validation_status")=="PASS"
            and proof.get("1930_full_legacy_acceptance")=="PASS"
            and proof.get("roy_portfolio_continuity")=="PASS"
            and proof.get("ai_paper_portfolio_continuity")=="PASS"
            and proof.get("transaction_ledger_continuity")=="PASS"
            and proof.get("new_intraday_fills")==0
            and proof.get("state_reinitialized") is False
            and proof.get("fallback_allowed") is False,
            "ROUTE_B_1930_ACCEPTANCE_PROOF_NOT_PASS")
    require(proof.get("current_state_id")==current_state.get("current_state_id")
            and proof.get("previous_state_id")==previous_state.get("current_state_id"),
            "ROUTE_B_1930_PROOF_LINEAGE_INVALID")
    require(current_state.get("previous_state_id")==previous_state.get("current_state_id")
            and current_state["decision"].get("previous_state_hash")==previous_state.get("decision_payload_hash"),
            "ROUTE_B_1930_CANONICAL_LINEAGE_INVALID")
    for key in ("top50","short_top30","long_top30"):
        require(current_state["decision"].get(key)==previous_state["decision"].get(key),
                "ROUTE_B_1930_RANKING_CONTINUITY_INVALID:"+key)
    run=_standard_base(current_state,previous_state,manifest,"19:30")
    run.update(
        production_data_gate="PASS",
        decision_state_continuity=True,
        portfolio_continuity=True,
        transaction_ledger_continuity=True,
        ranking_model_continuity=True,
        production_snapshot_id=proof.get("source_bundle_hash",run["production_snapshot_id"]),
    )
    return run


def collect_scheduled_run(
    repo_root: str | Path,
    artifacts_root: str | Path,
    source_artifacts: str | Path,
    store_root: str | Path,
    *,
    cadence: str,
    source_run_id: str,
) -> dict[str,Any]:
    policy=baseline_policy()
    if policy["status"]!="ACTIVE":
        return {
            "artifact":"RATE_ROUTE_B_ACCEPTANCE_COLLECTOR_RESULT_V1",
            "validation_status":"PASS",
            "collector_result":"NOOP_PENDING_BASELINE_BINDING",
            "session_written":False,
        }
    session=load_session(store_root)
    if session is None:
        return {
            "artifact":"RATE_ROUTE_B_ACCEPTANCE_COLLECTOR_RESULT_V1",
            "validation_status":"PASS",
            "collector_result":"NOOP_WAITING_FOR_ACTIVATION_SESSION",
            "session_written":False,
        }

    state_root=Path(artifacts_root)/"production_state"
    day,manifest=_find_slot(state_root,cadence,source_run_id)
    current=load_live_state(state_root,day,cadence)["state"]
    previous_cadence={"07:30":"19:30","09:30":"07:30","12:00":"09:30","19:30":"12:00"}[cadence]
    previous_day=_previous_legal_trading_day(day) if cadence=="07:30" else day
    previous=load_live_state(state_root,previous_day,previous_cadence)["state"]
    require(manifest.get("event_name")=="schedule"
            and str(manifest.get("workflow_run_id"))==str(source_run_id),
            "ROUTE_B_COLLECTOR_SOURCE_PROVENANCE_INVALID")

    ancestry=build_ancestry_evidence(
        repo_root,
        activation_merge_sha=session["activation_code_sha"],
        source_heads={cadence:manifest["commit_sha"]},
    )
    require(ancestry.get("validation_status")=="PASS",
            "ROUTE_B_COLLECTOR_ANCESTRY_NOT_PASS")
    row=ancestry["source_heads"][cadence]

    if cadence in {"09:30","12:00"}:
        overlay=validate_overlay(current,previous,manifest,source_run_id=str(source_run_id))
        run=bind_overlay_run_to_session(overlay,session,row)
    elif cadence=="07:30":
        raw=_build_0730(current,previous,manifest,source_artifacts)
        run=bind_standard_run_to_session(raw,session,row)
    elif cadence=="19:30":
        raw=_build_1930(current,previous,manifest,source_artifacts)
        run=bind_standard_run_to_session(raw,session,row)
    else:
        raise RouteBAcceptanceCollectorError("ROUTE_B_COLLECTOR_CADENCE_INVALID")

    stored=admit_run_to_store(store_root,run)
    return {
        "artifact":"RATE_ROUTE_B_ACCEPTANCE_COLLECTOR_RESULT_V1",
        "validation_status":"PASS",
        "collector_result":stored["store_result"],
        "trading_date":day,
        "cadence":cadence,
        "source_workflow_run_id":str(source_run_id),
        "source_head_sha":manifest.get("commit_sha"),
        "activation_code_sha":session.get("activation_code_sha"),
        "session_written":stored.get("session_written",False),
        "store_result":stored,
        "ancestry_evidence":ancestry,
    }

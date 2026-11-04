"""Route B Production evidence bridge.

Transforms Route B overlay/ancestry evidence into a verified activation object,
opens the CURRENT_PRODUCTION acceptance session on the next legal trading day,
and normalizes scheduled-run evidence for session admission.
"""
from __future__ import annotations

from typing import Any, Mapping, Sequence

from src.cer080_multi_day_continuity import resolve_next_trading_day
from src.production_acceptance_session import open_production_acceptance_session
from src.route_b_post_merge_activation import (
    ALLOWED_POINTER_PREFIXES,
    validate_route_b_post_merge_activation,
)


class RouteBAcceptanceBridgeError(RuntimeError):
    pass


def require(condition: bool, reason: str) -> None:
    if not condition:
        raise RouteBAcceptanceBridgeError(reason)


def _authorized_changes(changed: Any) -> bool:
    if not isinstance(changed,Sequence) or isinstance(changed,(str,bytes)):
        return False
    return all(
        isinstance(path,str)
        and any(path==prefix or path.startswith(prefix) for prefix in ALLOWED_POINTER_PREFIXES)
        for path in changed
    )


def build_activation_and_open_session(
    overlay_0930: Mapping[str,Any],
    overlay_1200: Mapping[str,Any],
    ancestry_evidence: Mapping[str,Any],
    *,
    activation_merge_sha: str,
) -> dict[str,Any]:
    activation=validate_route_b_post_merge_activation(
        overlay_0930,
        overlay_1200,
        ancestry_evidence,
        activation_merge_sha=activation_merge_sha,
    )
    calendar=resolve_next_trading_day(activation["trading_date"])
    require(calendar.get("status")=="PASS","ROUTE_B_SESSION_CALENDAR_NOT_PASS")
    start=calendar.get("next_trading_date")
    require(isinstance(start,str) and start,"ROUTE_B_SESSION_START_DATE_MISSING")
    session=open_production_acceptance_session(
        activation,
        session_start_date=start,
    )
    require(session.get("activation_code_sha")==activation_merge_sha,
            "ROUTE_B_SESSION_ACTIVATION_BINDING_INVALID")
    require(session.get("operational_head_policy")
            =="AUTHORIZED_DESCENDANT_POINTER_COMMITS_ONLY",
            "ROUTE_B_SESSION_OPERATIONAL_POLICY_INVALID")
    return {
        "artifact":"RATE_ROUTE_B_ACTIVATION_SESSION_BRIDGE_V1",
        "validation_status":"PASS",
        "route":"B_ZERO_FEE",
        "activation":activation,
        "session":session,
        "activation_trading_date":activation["trading_date"],
        "session_start_date":start,
        "trading_calendar_evidence":calendar,
        "activation_day_acceptance_credit_allowed":False,
        "historical_pre_activation_credit_allowed":False,
        "next_gate":"ACCUMULATE_CURRENT_PRODUCTION_SCHEDULED_RUNS",
    }


def bind_overlay_run_to_session(
    overlay: Mapping[str,Any],
    session: Mapping[str,Any],
    ancestry_row: Mapping[str,Any],
) -> dict[str,Any]:
    require(overlay.get("artifact")=="RATE_ROUTE_B_PRODUCTION_CHECKPOINT_ACCEPTANCE_V1"
            and overlay.get("validation_status")=="PASS"
            and overlay.get("route")=="B_ZERO_FEE",
            "ROUTE_B_RUN_OVERLAY_INVALID")
    cadence=overlay.get("cadence")
    require(cadence in {"09:30","12:00"},"ROUTE_B_RUN_CADENCE_INVALID")
    require(session.get("operational_head_policy")
            =="AUTHORIZED_DESCENDANT_POINTER_COMMITS_ONLY",
            "ROUTE_B_RUN_SESSION_POLICY_INVALID")
    require(ancestry_row.get("source_head_sha")==overlay.get("source_head_sha"),
            "ROUTE_B_RUN_HEAD_BINDING_INVALID")
    require(ancestry_row.get("activation_is_ancestor") is True,
            "ROUTE_B_RUN_ANCESTRY_NOT_PROVEN")
    changed=ancestry_row.get("changed_paths_since_activation")
    require(_authorized_changes(changed),"ROUTE_B_RUN_UNAUTHORIZED_OPERATIONAL_CHANGE")
    return {
        "event":"schedule",
        "validation_status":"PASS",
        "publish_result":"PASS",
        "trading_date":overlay.get("trading_date"),
        "cadence":cadence,
        "run_head_sha":overlay.get("source_head_sha"),
        "activation_code_sha":session.get("activation_code_sha"),
        "activation_binding_sha":session.get("activation_binding_sha"),
        "activation_is_ancestor":True,
        "operational_changes_authorized":True,
        "workflow_run_id":overlay.get("source_workflow_run_id"),
        "workflow_job_id":overlay.get("source_workflow_job_id"),
        "fallback_used":False,
        "automatic_retry_count":overlay.get("automatic_retry_count",0),
        "production_data_gate":overlay.get("production_data_gate"),
        "decision_state_continuity":overlay.get("decision_state_continuity"),
        "portfolio_continuity":overlay.get("portfolio_continuity"),
        "transaction_ledger_continuity":overlay.get("transaction_ledger_continuity"),
        "ranking_model_continuity":overlay.get("ranking_model_continuity"),
        "current_state_id":overlay.get("source_state_id"),
        "previous_state_id":overlay.get("previous_state_id"),
        "production_snapshot_id":overlay.get("source_state_hash"),
        "input_snapshot_id":overlay.get("source_state_hash"),
        "route_b_overlay_artifact":"RATE_ROUTE_B_PRODUCTION_CHECKPOINT_ACCEPTANCE_V1",
    }


def bind_standard_run_to_session(
    run: Mapping[str,Any],
    session: Mapping[str,Any],
    ancestry_row: Mapping[str,Any],
) -> dict[str,Any]:
    require(run.get("event")=="schedule" or run.get("event_name")=="schedule",
            "ROUTE_B_STANDARD_RUN_NOT_SCHEDULE")
    cadence=run.get("cadence")
    require(cadence in {"07:30","19:30"},"ROUTE_B_STANDARD_RUN_CADENCE_INVALID")
    head=run.get("run_head_sha") or run.get("commit_sha")
    require(ancestry_row.get("source_head_sha")==head,
            "ROUTE_B_STANDARD_RUN_HEAD_BINDING_INVALID")
    require(ancestry_row.get("activation_is_ancestor") is True,
            "ROUTE_B_STANDARD_RUN_ANCESTRY_NOT_PROVEN")
    require(_authorized_changes(ancestry_row.get("changed_paths_since_activation")),
            "ROUTE_B_STANDARD_RUN_UNAUTHORIZED_OPERATIONAL_CHANGE")
    normalized=dict(run)
    normalized["event"]="schedule"
    normalized["run_head_sha"]=head
    normalized["activation_code_sha"]=session.get("activation_code_sha")
    normalized["activation_binding_sha"]=session.get("activation_binding_sha")
    normalized["activation_is_ancestor"]=True
    normalized["operational_changes_authorized"]=True
    return normalized

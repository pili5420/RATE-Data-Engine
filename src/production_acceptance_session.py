"""RATE V11 CURRENT_PRODUCTION acceptance session and scheduled-run ledger.

This module replaces historical fixed soak dates with an activation-bound session.
It performs no scheduler or Production mutation.
"""
from __future__ import annotations

from datetime import date
from typing import Any, Mapping, Sequence

CADENCES=("07:30","09:30","12:00","19:30")
MIN_TRADING_DAYS=3
MIN_SCHEDULED_RUNS=12


class ProductionAcceptanceSessionError(RuntimeError):
    pass


def require(condition: bool, reason: str) -> None:
    if not condition:
        raise ProductionAcceptanceSessionError(reason)


def _iso_day(value: Any, reason: str) -> str:
    require(isinstance(value,str) and value,reason)
    try:
        parsed=date.fromisoformat(value)
    except ValueError as exc:
        raise ProductionAcceptanceSessionError(reason) from exc
    require(parsed.isoformat()==value,reason)
    return value


def open_production_acceptance_session(
    post_merge_activation: Mapping[str,Any],
    *,
    session_start_date: str,
) -> dict[str,Any]:
    require(isinstance(post_merge_activation,Mapping),
            "PA_SESSION_POST_MERGE_INVALID")
    require(
        post_merge_activation.get("artifact")
        == "RATE_POST_MERGE_PRODUCTION_ACTIVATION_VERIFICATION_V1"
        and post_merge_activation.get("validation_status")=="PASS"
        and post_merge_activation.get("final_disposition")=="PRODUCTION_ACTIVATION_VERIFIED",
        "PA_SESSION_ACTIVATION_NOT_VERIFIED",
    )
    require(post_merge_activation.get("production_credit")==1,
            "PA_SESSION_PRODUCTION_CREDIT_REQUIRED")
    require(post_merge_activation.get("cer081_credit")==0,
            "PA_SESSION_PREMATURE_CER081_CREDIT")
    main=post_merge_activation.get("merged_main_sha")
    require(isinstance(main,str) and len(main)==40,
            "PA_SESSION_MAIN_SHA_INVALID")
    activation_code_sha=post_merge_activation.get("activation_code_sha",main)
    require(isinstance(activation_code_sha,str) and len(activation_code_sha)==40,
            "PA_SESSION_ACTIVATION_CODE_SHA_INVALID")
    operational_head_policy=post_merge_activation.get(
        "operational_head_policy","EXACT_MERGED_MAIN_ONLY"
    )
    require(operational_head_policy in {
        "EXACT_MERGED_MAIN_ONLY",
        "AUTHORIZED_DESCENDANT_POINTER_COMMITS_ONLY",
    },"PA_SESSION_OPERATIONAL_HEAD_POLICY_INVALID")
    if operational_head_policy=="AUTHORIZED_DESCENDANT_POINTER_COMMITS_ONLY":
        require(post_merge_activation.get("route")=="B_ZERO_FEE",
                "PA_SESSION_DESCENDANT_POLICY_ROUTE_INVALID")
    start=_iso_day(session_start_date,"PA_SESSION_START_DATE_INVALID")

    return {
        "artifact":"RATE_V11_PRODUCTION_ACCEPTANCE_SESSION_V1",
        "validation_status":"PASS",
        "governance_scope":"CURRENT_PRODUCTION",
        "merged_main_sha":main,
        "activation_code_sha":activation_code_sha,
        "operational_head_policy":operational_head_policy,
        "session_start_date":start,
        "required_trading_days":MIN_TRADING_DAYS,
        "required_scheduled_runs":MIN_SCHEDULED_RUNS,
        "required_cadences":list(CADENCES),
        "official_event_required":"schedule",
        "manual_dispatch_credit_allowed":False,
        "historical_pre_activation_credit_allowed":False,
        "cross_main_credit_allowed":False,
        "duplicate_run_credit_allowed":False,
        "fallback_allowed":False,
        "automatic_recovery_credit_allowed":False,
        "accepted_runs":[],
        "trading_days_tested":0,
        "successful_cadence_runs":0,
        "missing_cadence_runs":12,
        "duplicate_cadence_runs":0,
        "completion_status":"IN_PROGRESS",
        "production_acceptance_granted":False,
        "cer081_credit":0,
    }


def _run_key(run: Mapping[str,Any]) -> tuple[str,str]:
    return (str(run.get("trading_date") or ""),str(run.get("cadence") or ""))


def admit_scheduled_run(
    session: Mapping[str,Any],
    run: Mapping[str,Any],
) -> dict[str,Any]:
    require(isinstance(session,Mapping)
            and session.get("artifact")=="RATE_V11_PRODUCTION_ACCEPTANCE_SESSION_V1"
            and session.get("validation_status")=="PASS",
            "PA_SESSION_INVALID")
    require(session.get("completion_status")=="IN_PROGRESS",
            "PA_SESSION_ALREADY_CLOSED")
    require(isinstance(run,Mapping),"PA_RUN_INVALID")
    require(run.get("event")=="schedule" or run.get("event_name")=="schedule",
            "PA_RUN_NOT_OFFICIAL_SCHEDULE")
    require(run.get("validation_status")=="PASS",
            "PA_RUN_NOT_PASS")
    require(run.get("publish_result") in (None,"PASS"),
            "PA_RUN_PUBLISH_NOT_PASS")
    require(run.get("fallback_used") is False,
            "PA_RUN_FALLBACK_USED")
    require(run.get("automatic_retry_count") in (None,0),
            "PA_RUN_AUTOMATIC_RETRY_USED")

    trading_date=_iso_day(run.get("trading_date"),"PA_RUN_TRADING_DATE_INVALID")
    cadence=run.get("cadence")
    require(cadence in CADENCES,"PA_RUN_CADENCE_INVALID")
    require(trading_date >= session["session_start_date"],
            "PA_RUN_PRE_SESSION_HISTORY_FORBIDDEN")
    operational_head=run.get("run_head_sha") or run.get("commit_sha")
    require(isinstance(operational_head,str) and len(operational_head)==40,
            "PA_RUN_OPERATIONAL_HEAD_INVALID")
    if session.get("operational_head_policy")=="EXACT_MERGED_MAIN_ONLY":
        require(operational_head==session["merged_main_sha"],
                "PA_RUN_MAIN_BINDING_MISMATCH")
    else:
        require(run.get("activation_code_sha")==session.get("activation_code_sha"),
                "PA_RUN_ACTIVATION_CODE_BINDING_MISMATCH")
        require(run.get("activation_is_ancestor") is True,
                "PA_RUN_ACTIVATION_ANCESTRY_NOT_PROVEN")
        require(run.get("operational_changes_authorized") is True,
                "PA_RUN_OPERATIONAL_CHANGES_NOT_AUTHORIZED")

    require(run.get("production_data_gate")=="PASS",
            "PA_RUN_PRODUCTION_DATA_GATE_NOT_PASS")
    require(run.get("decision_state_continuity") is True,
            "PA_RUN_STATE_CONTINUITY_NOT_PASS")
    require(run.get("portfolio_continuity") is True,
            "PA_RUN_PORTFOLIO_CONTINUITY_NOT_PASS")
    require(run.get("transaction_ledger_continuity") is True,
            "PA_RUN_LEDGER_CONTINUITY_NOT_PASS")
    require(run.get("ranking_model_continuity") in (True,"PASS"),
            "PA_RUN_RANKING_CONTINUITY_NOT_PASS")

    existing=list(session.get("accepted_runs") or [])
    key=(trading_date,cadence)
    require(key not in {_run_key(x) for x in existing if isinstance(x,Mapping)},
            "PA_RUN_DUPLICATE_FORBIDDEN")

    admitted={
        "trading_date":trading_date,
        "cadence":cadence,
        "workflow_run_id":run.get("workflow_run_id"),
        "workflow_job_id":run.get("workflow_job_id"),
        "run_head_sha":operational_head,
        "activation_code_sha":session.get("activation_code_sha"),
        "current_state_id":run.get("current_state_id"),
        "previous_state_id":run.get("previous_state_id"),
        "production_snapshot_id":run.get("production_snapshot_id"),
        "input_snapshot_id":run.get("input_snapshot_id"),
    }
    existing.append(admitted)

    unique={(x["trading_date"],x["cadence"]) for x in existing}
    days=sorted({d for d,_ in unique})
    complete_days=[d for d in days if all((d,c) in unique for c in CADENCES)]
    run_count=len(unique)
    return {
        **dict(session),
        "accepted_runs":existing,
        "trading_days_tested":len(complete_days),
        "successful_cadence_runs":run_count,
        "missing_cadence_runs":max(0,MIN_SCHEDULED_RUNS-run_count),
        "duplicate_cadence_runs":0,
        "completion_status":"READY_FOR_FINAL_ACCEPTANCE"
            if len(complete_days)>=MIN_TRADING_DAYS and run_count>=MIN_SCHEDULED_RUNS
            else "IN_PROGRESS",
    }



def audit_session_lineage(session: Mapping[str,Any]) -> dict[str,Any]:
    require(isinstance(session,Mapping)
            and session.get("artifact")=="RATE_V11_PRODUCTION_ACCEPTANCE_SESSION_V1",
            "PA_LINEAGE_SESSION_INVALID")
    runs=[dict(r) for r in (session.get("accepted_runs") or []) if isinstance(r,Mapping)]
    order={cadence:index for index,cadence in enumerate(CADENCES)}
    runs.sort(key=lambda r:(r.get("trading_date",""),order.get(r.get("cadence"),99)))
    require(runs,"PA_LINEAGE_NO_RUNS")

    for row in runs:
        require(isinstance(row.get("current_state_id"),str) and row["current_state_id"],
                "PA_LINEAGE_CURRENT_STATE_ID_MISSING")
        require(isinstance(row.get("previous_state_id"),str) and row["previous_state_id"],
                "PA_LINEAGE_PREVIOUS_STATE_ID_MISSING")

    within_day_links=0
    cross_day_links=0
    for previous,current in zip(runs,runs[1:]):
        require(current["previous_state_id"]==previous["current_state_id"],
                "PA_LINEAGE_STATE_CHAIN_BROKEN")
        if current["trading_date"]==previous["trading_date"]:
            within_day_links += 1
        else:
            require(previous["cadence"]=="19:30" and current["cadence"]=="07:30",
                    "PA_LINEAGE_CROSS_DAY_BOUNDARY_INVALID")
            cross_day_links += 1

    days=sorted({r["trading_date"] for r in runs})
    complete_days=[
        d for d in days
        if all(any(r["trading_date"]==d and r["cadence"]==cadence for r in runs)
               for cadence in CADENCES)
    ]
    return {
        "artifact":"RATE_V11_PRODUCTION_ACCEPTANCE_LINEAGE_AUDIT_V1",
        "validation_status":"PASS",
        "merged_main_sha":session["merged_main_sha"],
        "activation_code_sha":session.get("activation_code_sha"),
        "operational_head_policy":session.get("operational_head_policy"),
        "run_count":len(runs),
        "complete_trading_days":complete_days,
        "within_day_links_verified":within_day_links,
        "cross_day_links_verified":cross_day_links,
        "state_continuity":"PASS",
        "cross_day_continuity":"PASS" if len(complete_days) < 2 or cross_day_links >= len(complete_days)-1 else "FAIL",
        "reset_detected":False,
        "fork_detected":False,
    }

def summarize_production_acceptance_session(
    session: Mapping[str,Any],
) -> dict[str,Any]:
    require(isinstance(session,Mapping)
            and session.get("artifact")=="RATE_V11_PRODUCTION_ACCEPTANCE_SESSION_V1",
            "PA_SUMMARY_SESSION_INVALID")
    runs=session.get("accepted_runs") or []
    require(isinstance(runs,Sequence) and not isinstance(runs,(str,bytes)),
            "PA_SUMMARY_RUNS_INVALID")
    unique={(r.get("trading_date"),r.get("cadence")) for r in runs if isinstance(r,Mapping)}
    days=sorted({d for d,_ in unique if d})
    complete_days=[d for d in days if all((d,c) in unique for c in CADENCES)]
    ready=len(complete_days)>=MIN_TRADING_DAYS and len(unique)>=MIN_SCHEDULED_RUNS
    lineage=None
    if runs:
        lineage=audit_session_lineage(session)
    lineage_pass=(
        lineage is not None
        and lineage["state_continuity"]=="PASS"
        and lineage["cross_day_continuity"]=="PASS"
    )
    ready=ready and lineage_pass
    return {
        "artifact":"RATE_V11_PRODUCTION_ACCEPTANCE_SESSION_SUMMARY_V1",
        "validation_status":"PASS",
        "governance_scope":"CURRENT_PRODUCTION",
        "merged_main_sha":session["merged_main_sha"],
        "activation_code_sha":session.get("activation_code_sha"),
        "operational_head_policy":session.get("operational_head_policy"),
        "session_start_date":session["session_start_date"],
        "trading_days_tested":len(complete_days),
        "successful_cadence_runs":len(unique),
        "missing_cadence_runs":max(0,MIN_SCHEDULED_RUNS-len(unique)),
        "duplicate_cadence_runs":0,
        "full_4_cadence_scheduled_coverage":"PASS" if ready else "IN_PROGRESS",
        "state_continuity":"PASS" if lineage_pass else "IN_PROGRESS",
        "cross_day_continuity":"PASS" if lineage_pass else "IN_PROGRESS",
        "within_day_links_verified":0 if lineage is None else lineage["within_day_links_verified"],
        "cross_day_links_verified":0 if lineage is None else lineage["cross_day_links_verified"],
        "completion_status":"READY_FOR_CER081_FINAL_ACCEPTANCE" if ready else "IN_PROGRESS",
        "production_acceptance_granted":False,
        "cer081_credit":0,
        "complete_trading_days":complete_days,
        "next_gate":"CER081_FINAL_ACCEPTANCE" if ready else "ACCUMULATE_OFFICIAL_SCHEDULED_RUNS",
    }

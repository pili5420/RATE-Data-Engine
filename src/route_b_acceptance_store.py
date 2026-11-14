from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from src.cer074_acceptance import canonical
from src.production_acceptance_session import admit_scheduled_run, summarize_production_acceptance_session
from src.route_b_activation_package import build_runtime_package
from src.route_b_timing_provenance import verify_scheduled_source_from_actions, verify_timing_provenance
from src.route_b_store_transaction import load_committed_store, publish_store

SESSION_NAME="RATE_V11_PRODUCTION_ACCEPTANCE_SESSION.json"
SUMMARY_NAME="RATE_V11_PRODUCTION_ACCEPTANCE_SESSION_SUMMARY.json"
ACTIVATION_NAME="RATE_POST_MERGE_PRODUCTION_ACTIVATION_VERIFICATION.json"
PACKAGE_NAME="RATE_ROUTE_B_ACTIVATION_RUNTIME_PACKAGE.json"
ROOT=Path(__file__).resolve().parents[1]
STORE_ROOT=ROOT/"artifacts/production_acceptance/current"
SOURCE_ARTIFACTS_ROOT=ROOT/"source_artifacts"
FORBIDDEN_CLAIMS={"permit","permit_id","owner_permit","actor","actor_id","authorized_actor"}


class RouteBAcceptanceStoreError(RuntimeError):
    pass


def require(ok: bool, reason: str) -> None:
    if not ok:
        raise RouteBAcceptanceStoreError(reason)


def _read(path: Path) -> dict[str,Any]:
    try:
        value=json.loads(path.read_text(encoding="utf-8"))
    except (OSError,ValueError) as exc:
        raise RouteBAcceptanceStoreError("ROUTE_B_STORE_READ_FAILED") from exc
    require(isinstance(value,dict),"ROUTE_B_STORE_OBJECT_REQUIRED")
    return value


def load_session(store_root: str | Path) -> dict[str,Any] | None:
    snapshot=load_store_snapshot(store_root)
    return None if snapshot is None else snapshot["session"]


def _store_root(store_root: str | Path) -> Path:
    require(Path(store_root).resolve()==STORE_ROOT.resolve(),
            "ROUTE_B_STORE_DESTINATION_UNAUTHORIZED")
    return STORE_ROOT


def _reject_claims(value: Mapping[str,Any]) -> None:
    require(not (FORBIDDEN_CLAIMS & value.keys()),
            "ROUTE_B_STORE_CALLER_AUTHORITY_CLAIM_FORBIDDEN")


def load_store_snapshot(store_root: str | Path) -> dict[str,Any] | None:
    root=_store_root(store_root)
    committed=load_committed_store(root)
    if committed is None:
        return None
    files=committed["files"]
    session=files[SESSION_NAME]
    summary=files[SUMMARY_NAME]
    activation=files[ACTIVATION_NAME]
    package=files[PACKAGE_NAME]
    require(canonical(summary)==canonical(summarize_production_acceptance_session(session)),
            "ROUTE_B_STORE_SUMMARY_INCONSISTENT")
    require(package.get("activation")==activation and package.get("session",{}).get("activation_code_sha")
            ==session.get("activation_code_sha"),"ROUTE_B_STORE_ACTIVATION_INCONSISTENT")
    return {"transaction_id":committed["transaction_id"],
            "session":session,"summary":summary,"activation":activation,"package":package}


def persist_activation_package(package: Mapping[str,Any], store_root: str | Path, *,
                               source_run_id: str | None = None) -> dict[str,Any]:
    root=_store_root(store_root)
    _reject_claims(package)
    require(package.get("artifact")=="RATE_ROUTE_B_ACTIVATION_RUNTIME_PACKAGE_V1"
            and package.get("validation_status")=="PASS",
            "ROUTE_B_STORE_PACKAGE_INVALID")
    if package.get("runtime_mode")!="ACTIVE":
        return {
            "artifact":"RATE_ROUTE_B_ACCEPTANCE_STORE_RESULT_V1",
            "validation_status":"PASS",
            "store_result":"NOOP_INACTIVE_BASELINE",
            "session_written":False,
        }
    activation=package.get("activation")
    session=package.get("session")
    require(isinstance(activation,Mapping)
            and activation.get("final_disposition")=="PRODUCTION_ACTIVATION_VERIFIED",
            "ROUTE_B_STORE_ACTIVATION_INVALID")
    require(isinstance(session,Mapping)
            and session.get("artifact")=="RATE_V11_PRODUCTION_ACCEPTANCE_SESSION_V1",
            "ROUTE_B_STORE_SESSION_INVALID")
    require(isinstance(source_run_id,str) and source_run_id.isdecimal()
            and int(source_run_id)>0
            and str(package.get("overlay_1200",{}).get("source_workflow_run_id"))==source_run_id,
            "ROUTE_B_STORE_ACTIVATION_SOURCE_ID_REQUIRED")
    rebuilt=build_runtime_package(ROOT,ROOT/"artifacts",source_1200_run_id=source_run_id)
    require(canonical(rebuilt)==canonical(package),
            "ROUTE_B_STORE_ACTIVATION_SOURCE_MISMATCH")
    for cadence,key in (("09:30","overlay_0930"),("12:00","overlay_1200")):
        overlay=package[key]
        receipt=verify_scheduled_source_from_actions(
            run_id=overlay["source_workflow_run_id"],cadence=cadence,
            trading_date=overlay["trading_date"],head_sha=overlay["source_head_sha"])
        require(receipt.get("workflow_run_id")==str(overlay["source_workflow_run_id"])
                and receipt.get("run_attempt")==1,
                "ROUTE_B_STORE_ACTIVATION_SCHEDULE_UNVERIFIED")
    snapshot=load_store_snapshot(root)
    existing=None if snapshot is None else snapshot["session"]
    if existing is not None:
        same=(
            existing.get("activation_code_sha")==session.get("activation_code_sha")
            and existing.get("activation_binding_sha")==session.get("activation_binding_sha")
            and existing.get("session_start_date")==session.get("session_start_date")
            and existing.get("operational_head_policy")==session.get("operational_head_policy")
        )
        require(same,"ROUTE_B_STORE_ACTIVE_SESSION_CONFLICT")
        return {
            "artifact":"RATE_ROUTE_B_ACCEPTANCE_STORE_RESULT_V1",
            "validation_status":"PASS",
            "store_result":"IDEMPOTENT_NOOP_EXISTING_SESSION",
            "session_written":False,
            "activation_code_sha":existing.get("activation_code_sha"),
        }

    publish_store(root,{
        ACTIVATION_NAME:dict(activation),
        SESSION_NAME:dict(session),
        SUMMARY_NAME:summarize_production_acceptance_session(session),
        PACKAGE_NAME:dict(package),
    },expected_transaction_id=None)
    return {
        "artifact":"RATE_ROUTE_B_ACCEPTANCE_STORE_RESULT_V1",
        "validation_status":"PASS",
        "store_result":"SESSION_CREATED",
        "session_written":True,
        "activation_code_sha":session.get("activation_code_sha"),
        "session_start_date":session.get("session_start_date"),
    }


def admit_run_to_store(
    store_root: str | Path,
    run: Mapping[str,Any],
) -> dict[str,Any]:
    """Legacy direct-helper entry is permanently fail-closed."""
    _store_root(store_root)
    raise RouteBAcceptanceStoreError("ROUTE_B_STORE_DIRECT_ADMISSION_FORBIDDEN")


def _admit_verified_run_to_store(
    store_root: str | Path,
    run: Mapping[str,Any],
    *,source_artifacts: str | Path | None = None,
) -> dict[str,Any]:
    """Reconstruct business claims and replay GitHub evidence before writing."""
    root=_store_root(store_root)
    _reject_claims(run)
    require(source_artifacts is not None
            and Path(source_artifacts).resolve()==SOURCE_ARTIFACTS_ROOT.resolve(),
            "ROUTE_B_STORE_SOURCE_ARTIFACTS_UNAUTHORIZED")
    receipt=verify_timing_provenance(run)
    require(run.get("scheduler_timing_provenance")==receipt,
            "ROUTE_B_STORE_COLLECTOR_PROVENANCE_MISMATCH")
    run={**run,"run_attempt":1}
    snapshot=load_store_snapshot(root)
    session=None if snapshot is None else snapshot["session"]
    require(session is not None,"ROUTE_B_STORE_SESSION_MISSING")
    from src.route_b_acceptance_collector import reconstruct_scheduled_run
    rebuilt,_,_,_=reconstruct_scheduled_run(
        ROOT,ROOT/"artifacts",SOURCE_ARTIFACTS_ROOT,session,
        cadence=run.get("cadence"),source_run_id=str(run.get("workflow_run_id")))
    require(canonical(rebuilt)==canonical({k:v for k,v in run.items() if k!="run_attempt"}),
            "ROUTE_B_STORE_RECONSTRUCTED_CLAIMS_MISMATCH")
    trading_date=run.get("trading_date")
    cadence=run.get("cadence")
    require(isinstance(trading_date,str) and isinstance(cadence,str),
            "ROUTE_B_STORE_RUN_SLOT_INVALID")
    if trading_date < session["session_start_date"]:
        return {
            "artifact":"RATE_ROUTE_B_ACCEPTANCE_STORE_RESULT_V1",
            "validation_status":"PASS",
            "store_result":"NOOP_PRE_SESSION_RUN",
            "session_written":False,
            "trading_date":trading_date,
            "cadence":cadence,
        }

    existing=[
        row for row in session.get("accepted_runs",[])
        if row.get("trading_date")==trading_date and row.get("cadence")==cadence
    ]
    if existing:
        require(len(existing)==1,"ROUTE_B_STORE_DUPLICATE_LEDGER_CORRUPTION")
        row=existing[0]
        same=(
            str(row.get("workflow_run_id"))==str(run.get("workflow_run_id"))
            and row.get("current_state_id")==run.get("current_state_id")
            and row.get("run_head_sha")==run.get("run_head_sha")
        )
        require(same,"ROUTE_B_STORE_CONFLICTING_DUPLICATE_RUN")
        return {
            "artifact":"RATE_ROUTE_B_ACCEPTANCE_STORE_RESULT_V1",
            "validation_status":"PASS",
            "store_result":"IDEMPOTENT_NOOP_EXISTING_RUN",
            "session_written":False,
            "trading_date":trading_date,
            "cadence":cadence,
        }

    updated=admit_scheduled_run(session,run)
    summary=summarize_production_acceptance_session(updated)
    publish_store(root,{
        ACTIVATION_NAME:snapshot["activation"],
        SESSION_NAME:updated,
        SUMMARY_NAME:summary,
        PACKAGE_NAME:snapshot["package"],
    },expected_transaction_id=snapshot["transaction_id"])
    return {
        "artifact":"RATE_ROUTE_B_ACCEPTANCE_STORE_RESULT_V1",
        "validation_status":"PASS",
        "store_result":"RUN_ADMITTED",
        "session_written":True,
        "trading_date":trading_date,
        "cadence":cadence,
        "successful_cadence_runs":updated["successful_cadence_runs"],
        "trading_days_tested":updated["trading_days_tested"],
        "completion_status":summary["completion_status"],
    }

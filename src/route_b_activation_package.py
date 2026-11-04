from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from src.production_live_state import CADENCE_DIR, load_live_state, read_object
from src.route_b_acceptance_bridge import build_activation_and_open_session
from src.route_b_acceptance_overlay import validate_overlay
from src.route_b_git_ancestry import build_ancestry_evidence

ROOT=Path(__file__).resolve().parents[1]
BASELINE_PATH=ROOT/"config"/"RATE_ROUTE_B_ACTIVATION_BASELINE_V1.json"


class RouteBActivationPackageError(RuntimeError):
    pass


def require(ok: bool, reason: str) -> None:
    if not ok:
        raise RouteBActivationPackageError(reason)


def baseline_policy() -> dict[str,Any]:
    value=json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    require(value.get("artifact")=="RATE_ROUTE_B_ACTIVATION_BASELINE_V1",
            "ROUTE_B_BASELINE_ARTIFACT_INVALID")
    require(value.get("route")=="B_ZERO_FEE","ROUTE_B_BASELINE_ROUTE_INVALID")
    require(value.get("status") in {"PENDING_BINDING","ACTIVE"},
            "ROUTE_B_BASELINE_STATUS_INVALID")
    if value["status"]=="PENDING_BINDING":
        require(value.get("activation_merge_sha") is None
                and value.get("activation_binding_sha") is None
                and value.get("production_credit_allowed") is False,
                "ROUTE_B_PENDING_BASELINE_INVALID")
    else:
        sha=value.get("activation_merge_sha")
        binding=value.get("activation_binding_sha")
        require(isinstance(sha,str) and len(sha)==40
                and all(c in "0123456789abcdef" for c in sha),
                "ROUTE_B_ACTIVE_BASELINE_SHA_INVALID")
        require(isinstance(binding,str) and len(binding)==40
                and all(c in "0123456789abcdef" for c in binding)
                and binding != sha,
                "ROUTE_B_ACTIVE_BINDING_SHA_INVALID")
        require(value.get("production_credit_allowed") is True,
                "ROUTE_B_ACTIVE_BASELINE_CREDIT_INVALID")
    return value


def _find_slot(state_root: Path, cadence: str, run_id: str) -> tuple[str,dict[str,Any]]:
    slot=CADENCE_DIR[cadence]
    matches=[]
    live=state_root/"live"
    if live.exists():
        for day in sorted(live.iterdir()):
            manifest_path=day/slot/"RATE_PRODUCTION_STATE_MANIFEST.json"
            if not manifest_path.is_file():
                continue
            manifest=read_object(manifest_path)
            if manifest.get("cadence")==cadence and str(manifest.get("workflow_run_id"))==str(run_id):
                matches.append((day.name,manifest))
    require(len(matches)==1,"ROUTE_B_ACTIVATION_SOURCE_SLOT_MATCH_COUNT_INVALID")
    return matches[0]


def build_runtime_package(
    repo_root: str | Path,
    artifacts_root: str | Path,
    *,
    source_1200_run_id: str,
) -> dict[str,Any]:
    policy=baseline_policy()
    if policy["status"]=="PENDING_BINDING":
        return {
            "artifact":"RATE_ROUTE_B_ACTIVATION_RUNTIME_PACKAGE_V1",
            "validation_status":"PASS",
            "runtime_mode":"NOOP_PENDING_BASELINE_BINDING",
            "production_credit":0,
            "session_opened":False,
            "next_gate":"FINAL_ENGINEERING_FREEZE_BINDING",
        }

    root=Path(artifacts_root)
    state_root=root/"production_state"
    day,manifest_1200=_find_slot(state_root,"12:00",source_1200_run_id)
    state_1200=load_live_state(state_root,day,"12:00")["state"]
    state_0930=load_live_state(state_root,day,"09:30")["state"]
    state_0730=load_live_state(state_root,day,"07:30")["state"]
    manifest_0930=load_live_state(state_root,day,"09:30")["manifest"]

    overlay_0930=validate_overlay(
        state_0930,state_0730,manifest_0930,
        source_run_id=str(manifest_0930["workflow_run_id"]),
    )
    overlay_1200=validate_overlay(
        state_1200,state_0930,manifest_1200,
        source_run_id=str(source_1200_run_id),
    )

    ancestry=build_ancestry_evidence(
        repo_root,
        activation_merge_sha=policy["activation_merge_sha"],
        activation_binding_sha=policy["activation_binding_sha"],
        source_heads={
            "09:30":overlay_0930["source_head_sha"],
            "12:00":overlay_1200["source_head_sha"],
        },
    )
    require(ancestry.get("validation_status")=="PASS",
            "ROUTE_B_ACTIVATION_ANCESTRY_NOT_PASS")
    bridge=build_activation_and_open_session(
        overlay_0930,overlay_1200,ancestry,
        activation_merge_sha=policy["activation_merge_sha"],
    )
    return {
        "artifact":"RATE_ROUTE_B_ACTIVATION_RUNTIME_PACKAGE_V1",
        "validation_status":"PASS",
        "runtime_mode":"ACTIVE",
        "route":"B_ZERO_FEE",
        "activation_baseline":policy,
        "overlay_0930":overlay_0930,
        "overlay_1200":overlay_1200,
        "ancestry_evidence":ancestry,
        "activation":bridge["activation"],
        "session":bridge["session"],
        "trading_calendar_evidence":bridge["trading_calendar_evidence"],
        "production_credit":1,
        "session_opened":True,
        "next_gate":"PERSIST_CURRENT_PRODUCTION_ACCEPTANCE_SESSION",
    }

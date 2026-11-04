from __future__ import annotations
from typing import Any, Mapping, Sequence

class RouteBPostMergeActivationError(RuntimeError):
    pass

def require(ok: bool, reason: str) -> None:
    if not ok:
        raise RouteBPostMergeActivationError(reason)

ALLOWED_POINTER_PREFIXES=(
    "artifacts/RATE_PRODUCTION_SOURCE_BUNDLE_LATEST.json",
    "artifacts/production_source_snapshots/",
    "artifacts/RATE_PRODUCTION_STATE_LATEST.json",
    "artifacts/production_state/live/",
)

def _sha(value: Any) -> bool:
    return isinstance(value,str) and len(value)==40 and all(c in "0123456789abcdef" for c in value)

def _overlay(value: Mapping[str,Any], cadence: str) -> None:
    require(value.get("artifact")=="RATE_ROUTE_B_PRODUCTION_CHECKPOINT_ACCEPTANCE_V1",
            "ROUTE_B_ACTIVATION_OVERLAY_ARTIFACT_INVALID")
    require(value.get("validation_status")=="PASS"
            and value.get("route")=="B_ZERO_FEE"
            and value.get("cadence")==cadence
            and value.get("source_event_name")=="schedule"
            and value.get("production_data_gate")=="PASS"
            and value.get("decision_state_continuity") is True
            and value.get("portfolio_continuity") is True
            and value.get("transaction_ledger_continuity") is True
            and value.get("ranking_model_continuity") is True
            and value.get("fallback_used") is False
            and value.get("scheduled_soak_credit") is True
            and value.get("production_acceptance_eligible") is True
            and value.get("canonical_state_mutated") is False
            and value.get("cer081_credit")==0,
            "ROUTE_B_ACTIVATION_OVERLAY_NOT_PASS")
    require(value.get("current_intraday_price") is None
            and value.get("current_intraday_volume") is None
            and value.get("intraday_rerank_performed") is False
            and value.get("paper_trade_fill_count")==0,
            "ROUTE_B_ACTIVATION_INTRADAY_VALUE_OR_ACTION_FORBIDDEN")
    require(_sha(value.get("source_head_sha")),"ROUTE_B_ACTIVATION_SOURCE_HEAD_INVALID")

def validate_route_b_post_merge_activation(
    overlay_0930: Mapping[str,Any],
    overlay_1200: Mapping[str,Any],
    ancestry_evidence: Mapping[str,Any],
    *,
    activation_merge_sha: str,
) -> dict[str,Any]:
    require(_sha(activation_merge_sha),"ROUTE_B_ACTIVATION_BASELINE_SHA_INVALID")
    _overlay(overlay_0930,"09:30")
    _overlay(overlay_1200,"12:00")
    require(overlay_0930.get("trading_date")==overlay_1200.get("trading_date"),
            "ROUTE_B_ACTIVATION_TRADING_DATE_MISMATCH")
    require(overlay_1200.get("previous_state_id")==overlay_0930.get("source_state_id"),
            "ROUTE_B_ACTIVATION_0930_1200_LINEAGE_INVALID")

    require(ancestry_evidence.get("artifact")=="RATE_ROUTE_B_GIT_ANCESTRY_EVIDENCE_V1"
            and ancestry_evidence.get("validation_status")=="PASS",
            "ROUTE_B_ACTIVATION_ANCESTRY_EVIDENCE_INVALID")
    require(ancestry_evidence.get("activation_merge_sha")==activation_merge_sha,
            "ROUTE_B_ACTIVATION_ANCESTRY_BASELINE_MISMATCH")
    heads=ancestry_evidence.get("source_heads")
    require(isinstance(heads,Mapping),"ROUTE_B_ACTIVATION_ANCESTRY_HEADS_INVALID")
    for cadence,overlay in (("09:30",overlay_0930),("12:00",overlay_1200)):
        row=heads.get(cadence)
        require(isinstance(row,Mapping)
                and row.get("source_head_sha")==overlay.get("source_head_sha")
                and row.get("activation_is_ancestor") is True,
                "ROUTE_B_ACTIVATION_ANCESTRY_NOT_PROVEN:"+cadence)
        changed=row.get("changed_paths_since_activation")
        require(isinstance(changed,Sequence) and not isinstance(changed,(str,bytes)),
                "ROUTE_B_ACTIVATION_CHANGED_PATHS_INVALID:"+cadence)
        for path in changed:
            require(isinstance(path,str)
                    and any(path==prefix or path.startswith(prefix) for prefix in ALLOWED_POINTER_PREFIXES),
                    "ROUTE_B_ACTIVATION_UNAUTHORIZED_POST_MERGE_CHANGE:"+str(path))

    return {
        "artifact":"RATE_POST_MERGE_PRODUCTION_ACTIVATION_VERIFICATION_V1",
        "validation_status":"PASS",
        "final_disposition":"PRODUCTION_ACTIVATION_VERIFIED",
        "route":"B_ZERO_FEE",
        "activation_code_sha":activation_merge_sha,
        "merged_main_sha":activation_merge_sha,
        "operational_head_policy":"AUTHORIZED_DESCENDANT_POINTER_COMMITS_ONLY",
        "trading_date":overlay_0930["trading_date"],
        "0930_source_head_sha":overlay_0930["source_head_sha"],
        "1200_source_head_sha":overlay_1200["source_head_sha"],
        "0930_route_b_checkpoint":"PASS",
        "1200_route_b_checkpoint":"PASS",
        "current_intraday_price_required":False,
        "fallback_used":False,
        "production_credit":1,
        "cer081_credit":0,
        "next_gate":"OPEN_CURRENT_PRODUCTION_ACCEPTANCE_SESSION"
    }

"""Post-merge Production activation verification for RATE intraday.

A merge alone grants no Production credit. PASS requires the merged activation
configuration plus successful official scheduled 09:30 and 12:00 runtime evidence.
"""
from __future__ import annotations
from typing import Any, Mapping, Sequence
from .intraday_activation_candidate_review import canonical_digest

class PostMergeActivationVerificationError(RuntimeError): pass
def require(condition: bool, reason: str) -> None:
    if not condition:
        raise PostMergeActivationVerificationError(reason)

REQUIRED_MARKETS={"TWSE":25,"TPEX":5}
REQUIRED_CADENCES={"09:30","12:00"}

def _validate_run(run: Mapping[str,Any], cadence: str) -> None:
    require(run.get("event")=="schedule","POST_MERGE_RUNTIME_EVENT_NOT_SCHEDULE")
    require(run.get("cadence")==cadence,"POST_MERGE_RUNTIME_CADENCE_MISMATCH")
    require(run.get("validation_status")=="PASS","POST_MERGE_RUNTIME_NOT_PASS")
    require(run.get("authorized_intraday_feed")=="PASS","POST_MERGE_INTRADAY_FEED_NOT_PASS")
    require(run.get("coverage")=="30/30"
            and run.get("market_counts")==REQUIRED_MARKETS,
            "POST_MERGE_INTRADAY_COVERAGE_INVALID")
    require(run.get("market_intraday_price_gate")=="PASS"
            and run.get("full_intraday_decision_status")=="PASS",
            "POST_MERGE_DECISION_GATE_NOT_PASS")
    require(run.get("fallback_used") is False
            and run.get("automatic_retry_count")==0,
            "POST_MERGE_FALLBACK_OR_RETRY_INVALID")
    require(run.get("production_data_gate")=="PASS"
            and run.get("decision_state_continuity") is True
            and run.get("portfolio_continuity") is True
            and run.get("transaction_ledger_continuity") is True,
            "POST_MERGE_CONTINUITY_GATE_INVALID")
    require(run.get("production_snapshot_id")
            and run.get("input_snapshot_id"),
            "POST_MERGE_SNAPSHOT_BINDING_MISSING")

def validate_post_merge_production_activation(
    evidence: Mapping[str,Any],
    *,
    expected_evidence_sha256: str,
    expected_pre_merge_main_sha: str,
    expected_merged_main_sha: str,
    expected_activation_pr_number: int,
    expected_activation_commit_sha: str,
    expected_provider_name: str="Fugle",
) -> dict[str,Any]:
    require(canonical_digest(evidence)==expected_evidence_sha256,
            "POST_MERGE_EVIDENCE_HASH_MISMATCH")
    require(evidence.get("artifact")=="RATE_POST_MERGE_PRODUCTION_ACTIVATION_EVIDENCE_V1"
            and evidence.get("merge_status")=="PASS",
            "POST_MERGE_EVIDENCE_NOT_PASS")
    require(evidence.get("pre_merge_main_sha")==expected_pre_merge_main_sha
            and evidence.get("merged_main_sha")==expected_merged_main_sha
            and evidence.get("activation_pr_number")==expected_activation_pr_number
            and evidence.get("activation_commit_sha")==expected_activation_commit_sha,
            "POST_MERGE_MERGE_BINDING_MISMATCH")
    require(evidence.get("activation_pr_merged") is True
            and evidence.get("merge_commit_on_main") is True,
            "POST_MERGE_PR_NOT_MERGED")

    cfg=evidence.get("configuration")
    require(isinstance(cfg,Mapping),"POST_MERGE_CONFIGURATION_MISSING")
    dep=cfg.get("external_dependency")
    require(isinstance(dep,Mapping)
            and dep.get("dependency_id")=="EXTERNAL_AUTHORIZED_INTRADAY_FEED_DEPENDENCY"
            and dep.get("status")=="PASS"
            and dep.get("engineering_resolution_available") is True
            and dep.get("required_market_coverage")==["TWSE","TPEX"]
            and dep.get("fallback_allowed") is False,
            "POST_MERGE_DEPENDENCY_CONFIG_INVALID")
    reg=cfg.get("source_registry")
    require(isinstance(reg,Mapping)
            and reg.get("provider")==expected_provider_name
            and reg.get("authorization_status")=="PASS"
            and reg.get("operational_use_allowed") is True
            and reg.get("intraday_status")=={
                "0930":"AUTHORIZED_PROVIDER_READY",
                "1200":"AUTHORIZED_PROVIDER_READY",
            },
            "POST_MERGE_SOURCE_REGISTRY_INVALID")
    official=cfg.get("official_registry")
    require(isinstance(official,Mapping)
            and official.get("dataset_id")=="authorized_market_intraday"
            and official.get("authority")==expected_provider_name
            and official.get("authorization_status")=="PASS"
            and official.get("blocked_dependency_present") is False
            and official.get("fallback_allowed") is False
            and official.get("cadence_applicability",{}).get("09:30")=="REQUIRED"
            and official.get("cadence_applicability",{}).get("12:00")=="REQUIRED",
            "POST_MERGE_OFFICIAL_REGISTRY_INVALID")
    phase2=cfg.get("phase2")
    require(isinstance(phase2,Mapping)
            and phase2.get("intraday_authority")=="PASS"
            and phase2.get("0930_price_gate")=="PASS"
            and phase2.get("1200_price_gate")=="PASS",
            "POST_MERGE_PHASE2_CONFIG_INVALID")
    sched=cfg.get("schedulers")
    require(isinstance(sched,Mapping),"POST_MERGE_SCHEDULER_CONFIG_MISSING")
    for cadence in REQUIRED_CADENCES:
        s=sched.get(cadence)
        require(isinstance(s,Mapping)
                and s.get("authorized_feed_path_bound") is True
                and s.get("execution_authority")=="MAIN_ONLY"
                and s.get("provider_build_step_present") is True,
                "POST_MERGE_SCHEDULER_CONFIG_INVALID:"+cadence)

    runs=evidence.get("scheduled_runs")
    require(isinstance(runs,Sequence) and not isinstance(runs,(str,bytes))
            and len(runs)==2,
            "POST_MERGE_SCHEDULED_RUN_SET_INVALID")
    by={r.get("cadence"):r for r in runs if isinstance(r,Mapping)}
    require(set(by)==REQUIRED_CADENCES,"POST_MERGE_SCHEDULED_RUN_CADENCES_INVALID")
    _validate_run(by["09:30"],"09:30")
    _validate_run(by["12:00"],"12:00")
    require(by["12:00"].get("previous_state_id")==by["09:30"].get("current_state_id"),
            "POST_MERGE_INTRADAY_STATE_CHAIN_BROKEN")

    require(evidence.get("blocking_defects")==[]
            and evidence.get("merge_rollback_performed") is False,
            "POST_MERGE_BLOCKING_DEFECT_PRESENT")
    return {
      "artifact":"RATE_POST_MERGE_PRODUCTION_ACTIVATION_VERIFICATION_V1",
      "validation_status":"PASS",
      "final_disposition":"PRODUCTION_ACTIVATION_VERIFIED",
      "merged_main_sha":expected_merged_main_sha,
      "activation_pr_number":expected_activation_pr_number,
      "provider_name":expected_provider_name,
      "scheduled_runs":"2/2",
      "intraday_market_coverage":"30/30",
      "market_counts":dict(REQUIRED_MARKETS),
      "state_chain_continuity":True,
      "fallback_used":False,
      "production_credit":1,
      "cer081_credit":0,
      "next_gate":"CER081_PRODUCTION_ACCEPTANCE",
    }

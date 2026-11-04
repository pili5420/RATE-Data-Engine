"""Final RATE V11 CER-081 Production acceptance gate.

This validator composes the post-merge intraday activation verification with the
existing CER-081 unattended multi-day soak artifacts. It performs no scheduler,
GitHub, provider, registry, or Production mutation.
"""
from __future__ import annotations
from typing import Any, Mapping
from .intraday_activation_candidate_review import canonical_digest


class CER081FinalAcceptanceError(RuntimeError):
    pass


def require(condition: bool, reason: str) -> None:
    if not condition:
        raise CER081FinalAcceptanceError(reason)


def validate_cer081_final_production_acceptance(
    post_merge_activation: Mapping[str, Any],
    soak_summary: Mapping[str, Any],
    scheduler_summary: Mapping[str, Any],
    deterministic_summary: Mapping[str, Any],
    model_freeze_summary: Mapping[str, Any],
    *,
    expected_post_merge_sha256: str,
    expected_soak_summary_sha256: str,
    expected_scheduler_summary_sha256: str,
    expected_deterministic_summary_sha256: str,
    expected_model_freeze_summary_sha256: str,
    expected_merged_main_sha: str,
) -> dict[str, Any]:
    require(
        canonical_digest(post_merge_activation) == expected_post_merge_sha256,
        "CER081_FINAL_POST_MERGE_HASH_MISMATCH",
    )
    require(
        post_merge_activation.get("artifact")
        == "RATE_POST_MERGE_PRODUCTION_ACTIVATION_VERIFICATION_V1"
        and post_merge_activation.get("validation_status") == "PASS"
        and post_merge_activation.get("final_disposition")
        == "PRODUCTION_ACTIVATION_VERIFIED",
        "CER081_FINAL_POST_MERGE_NOT_PASS",
    )
    require(
        post_merge_activation.get("merged_main_sha") == expected_merged_main_sha,
        "CER081_FINAL_MAIN_BINDING_MISMATCH",
    )
    require(
        post_merge_activation.get("scheduled_runs") == "2/2"
        and post_merge_activation.get("intraday_market_coverage") == "30/30"
        and post_merge_activation.get("market_counts")
        == {"TWSE": 25, "TPEX": 5}
        and post_merge_activation.get("state_chain_continuity") is True
        and post_merge_activation.get("fallback_used") is False
        and post_merge_activation.get("production_credit") == 1
        and post_merge_activation.get("cer081_credit") == 0,
        "CER081_FINAL_INTRADAY_ACTIVATION_BOUNDARY_INVALID",
    )

    require(
        canonical_digest(soak_summary) == expected_soak_summary_sha256,
        "CER081_FINAL_SOAK_HASH_MISMATCH",
    )
    require(
        soak_summary.get("artifact") == "RATE_CER081_SOAK_SUMMARY"
        and soak_summary.get("validation_status") == "PASS"
        and soak_summary.get("final_result") == "PASS"
        and soak_summary.get("completion_status") == "ACCEPTED_CLOSED",
        "CER081_FINAL_SOAK_NOT_ACCEPTED",
    )
    require(
        soak_summary.get("governance_scope") == "CURRENT_PRODUCTION"
        and soak_summary.get("CER081_FULL_PRODUCTION_SOAK") == "PASS"
        and soak_summary.get("production_acceptance_granted") is True,
        "CER081_FINAL_GOVERNANCE_SCOPE_INVALID",
    )
    require(
        isinstance(soak_summary.get("trading_days_tested"), int)
        and soak_summary["trading_days_tested"] >= 3
        and isinstance(soak_summary.get("successful_cadence_runs"), int)
        and soak_summary["successful_cadence_runs"] >= 12
        and soak_summary.get("missing_cadence_runs") == 0
        and soak_summary.get("duplicate_cadence_runs") == 0
        and soak_summary.get("report_only_run_count") == 0,
        "CER081_FINAL_SCHEDULED_RUN_METRICS_INVALID",
    )
    require(
        soak_summary.get("full_4_cadence_scheduled_coverage") == "PASS"
        and soak_summary.get("state_continuity") == "PASS"
        and soak_summary.get("cross_day_continuity") == "PASS"
        and soak_summary.get("portfolio_continuity") == "PASS"
        and soak_summary.get("transaction_ledger_continuity") == "PASS"
        and soak_summary.get("ranking_model_continuity") == "PASS",
        "CER081_FINAL_CONTINUITY_NOT_PASS",
    )
    require(
        soak_summary.get("remaining_blockers") == []
        and soak_summary.get("unrecovered_failure_count") == 0
        and soak_summary.get("duplicate_production_record_count") == 0
        and soak_summary.get("automatic_recovery_count") == 0,
        "CER081_FINAL_BLOCKERS_PRESENT",
    )
    require(
        soak_summary.get("soak_credit_allowed_while_blocked") is False
        and soak_summary.get("cer081_completion_allowed_while_blocked") is False
        and soak_summary.get("production_acceptance_allowed_while_blocked") is False,
        "CER081_FINAL_BLOCKED_GOVERNANCE_CHANGED",
    )

    require(
        canonical_digest(scheduler_summary) == expected_scheduler_summary_sha256,
        "CER081_FINAL_SCHEDULER_HASH_MISMATCH",
    )
    require(
        scheduler_summary.get("artifact")
        == "RATE_CER081_SCHEDULER_RELIABILITY_SUMMARY"
        and scheduler_summary.get("validation_status") == "PASS"
        and scheduler_summary.get("scheduler_coverage") == "PASS"
        and scheduler_summary.get("manual_dispatch_substitution") == "NO"
        and scheduler_summary.get("missed_execution_count") == 0
        and scheduler_summary.get("delayed_execution_blocking_count") == 0,
        "CER081_FINAL_SCHEDULER_NOT_PASS",
    )

    require(
        canonical_digest(deterministic_summary)
        == expected_deterministic_summary_sha256,
        "CER081_FINAL_DETERMINISTIC_HASH_MISMATCH",
    )
    require(
        deterministic_summary.get("artifact")
        == "RATE_CER081_DETERMINISTIC_REPLAY_SUMMARY"
        and deterministic_summary.get("validation_status") == "PASS"
        and deterministic_summary.get("deterministic_audit_replay") == "PASS"
        and deterministic_summary.get("replay_new_record_count") == 0,
        "CER081_FINAL_DETERMINISTIC_NOT_PASS",
    )

    require(
        canonical_digest(model_freeze_summary)
        == expected_model_freeze_summary_sha256,
        "CER081_FINAL_MODEL_FREEZE_HASH_MISMATCH",
    )
    require(
        model_freeze_summary.get("artifact") == "RATE_CER081_MODEL_FREEZE_SUMMARY"
        and model_freeze_summary.get("validation_status") == "PASS"
        and model_freeze_summary.get("model_freeze_integrity") == "PASS"
        and model_freeze_summary.get("production_rule_auto_upgrade") == "NO"
        and model_freeze_summary.get("change_control_required_for_model_changes")
        == "PASS",
        "CER081_FINAL_MODEL_FREEZE_NOT_PASS",
    )

    return {
        "artifact": "RATE_V11_FINAL_PRODUCTION_ACCEPTANCE_V1",
        "validation_status": "PASS",
        "final_disposition": "RATE_V11_PRODUCTION_ACCEPTED",
        "cer081_status": "CER081_ACCEPTED_CLOSED",
        "merged_main_sha": expected_merged_main_sha,
        "production_activation_verified": True,
        "trading_days_tested": soak_summary["trading_days_tested"],
        "scheduled_runs_accepted": soak_summary["successful_cadence_runs"],
        "full_four_cadence_coverage": True,
        "intraday_coverage": "30/30",
        "state_continuity": True,
        "cross_day_continuity": True,
        "portfolio_continuity": True,
        "transaction_ledger_continuity": True,
        "deterministic_replay": True,
        "model_freeze": True,
        "fallback_used": False,
        "blocking_defects": 0,
        "production_credit": 1,
        "cer081_credit": 1,
        "development_status": "COMPLETE",
        "next_gate": "NONE_ENGINEERING_COMPLETE",
    }

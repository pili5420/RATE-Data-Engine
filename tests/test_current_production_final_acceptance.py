from __future__ import annotations
import unittest

from src.current_production_final_acceptance import (
    CurrentProductionFinalAcceptanceError,
    validate_current_production_final_acceptance,
)
from src.intraday_activation_candidate_review import canonical_digest

MAIN="a"*40
BIND="d"*40

def post():
    return {
        "artifact":"RATE_POST_MERGE_PRODUCTION_ACTIVATION_VERIFICATION_V1",
        "validation_status":"PASS",
        "final_disposition":"PRODUCTION_ACTIVATION_VERIFIED",
        "merged_main_sha":MAIN,
        "production_credit":1,
        "cer081_credit":0,
    }

def post_route_b():
    return {
        "artifact":"RATE_POST_MERGE_PRODUCTION_ACTIVATION_VERIFICATION_V1",
        "validation_status":"PASS",
        "final_disposition":"PRODUCTION_ACTIVATION_VERIFIED",
        "route":"B_ZERO_FEE",
        "merged_main_sha":MAIN,
        "activation_code_sha":MAIN,
        "activation_binding_sha":BIND,
        "operational_head_policy":"AUTHORIZED_DESCENDANT_POINTER_COMMITS_ONLY",
        "production_credit":1,
        "cer081_credit":0,
    }

def session():
    return {
        "artifact":"RATE_V11_PRODUCTION_ACCEPTANCE_SESSION_SUMMARY_V1",
        "validation_status":"PASS",
        "governance_scope":"CURRENT_PRODUCTION",
        "merged_main_sha":MAIN,
        "session_start_date":"2026-11-05",
        "trading_days_tested":3,
        "successful_cadence_runs":12,
        "missing_cadence_runs":0,
        "duplicate_cadence_runs":0,
        "full_4_cadence_scheduled_coverage":"PASS",
        "state_continuity":"PASS",
        "cross_day_continuity":"PASS",
        "official_schedule_only":"PASS",
        "production_data_gate":"PASS",
        "decision_state_evidence":"PASS",
        "portfolio_continuity":"PASS",
        "transaction_ledger_continuity":"PASS",
        "ranking_model_continuity":"PASS",
        "fallback_free":"PASS",
        "automatic_retry_free":"PASS",
        "completion_status":"READY_FOR_CER081_FINAL_ACCEPTANCE",
        "production_acceptance_granted":False,
        "cer081_credit":0,
    }

def scheduler():
    return {
        "artifact":"RATE_CER081_SCHEDULER_RELIABILITY_SUMMARY",
        "validation_status":"PASS",
        "scheduler_coverage":"PASS",
        "manual_dispatch_substitution":"NO",
        "missed_execution_count":0,
        "actual_timing_evidence":"PASS",
        "actual_timing_missing_or_invalid_count":0,
        "delayed_execution_blocking_count":0,
    }

def deterministic():
    return {
        "artifact":"RATE_CER081_DETERMINISTIC_REPLAY_SUMMARY",
        "validation_status":"PASS",
        "deterministic_audit_replay":"PASS",
        "replay_new_record_count":0,
    }

def freeze():
    return {
        "artifact":"RATE_CER081_MODEL_FREEZE_SUMMARY",
        "validation_status":"PASS",
        "model_freeze_integrity":"PASS",
        "production_rule_auto_upgrade":"NO",
        "change_control_required_for_model_changes":"PASS",
    }

class FinalAcceptanceTests(unittest.TestCase):
    def validate(self,p=None,s=None,sch=None,d=None,f=None,**kw):
        p=p or post(); s=s or session(); sch=sch or scheduler(); d=d or deterministic(); f=f or freeze()
        return validate_current_production_final_acceptance(
            p,s,sch,d,f,
            expected_post_merge_sha256=kw.get("ph",canonical_digest(p)),
            expected_session_summary_sha256=kw.get("sh",canonical_digest(s)),
            expected_scheduler_summary_sha256=kw.get("schh",canonical_digest(sch)),
            expected_deterministic_summary_sha256=kw.get("dh",canonical_digest(d)),
            expected_model_freeze_summary_sha256=kw.get("fh",canonical_digest(f)),
            expected_merged_main_sha=kw.get("main",MAIN),
        )

    def test_full_pass_closes_production_acceptance(self):
        result=self.validate()
        self.assertEqual(result["final_disposition"],"RATE_V11_PRODUCTION_ACCEPTED")
        self.assertEqual(result["cer081_status"],"CER081_ACCEPTED_CLOSED")
        self.assertEqual(result["development_status"],"COMPLETE")

    def test_session_must_be_current_production_ready(self):
        s=session(); s["completion_status"]="IN_PROGRESS"
        with self.assertRaisesRegex(CurrentProductionFinalAcceptanceError,"SESSION_NOT_READY"):
            self.validate(s=s)

    def test_three_days_twelve_runs_required(self):
        s=session(); s["trading_days_tested"]=2
        with self.assertRaisesRegex(CurrentProductionFinalAcceptanceError,"RUN_METRICS_INVALID"):
            self.validate(s=s)
        s=session(); s["successful_cadence_runs"]=11
        with self.assertRaisesRegex(CurrentProductionFinalAcceptanceError,"RUN_METRICS_INVALID"):
            self.validate(s=s)

    def test_cross_day_continuity_required(self):
        s=session(); s["cross_day_continuity"]="FAIL"
        with self.assertRaisesRegex(CurrentProductionFinalAcceptanceError,"CONTINUITY_NOT_PASS"):
            self.validate(s=s)

    def test_business_continuity_is_independent_final_gate(self):
        for key in ("portfolio_continuity","transaction_ledger_continuity","ranking_model_continuity"):
            s=session(); s[key]="FAIL"
            with self.subTest(key=key):
                with self.assertRaisesRegex(CurrentProductionFinalAcceptanceError,"BUSINESS_CONTINUITY_NOT_PASS"):
                    self.validate(s=s)

    def test_session_guards_are_independent_final_gate(self):
        for key in ("official_schedule_only","production_data_gate","decision_state_evidence","fallback_free","automatic_retry_free"):
            s=session(); s[key]="FAIL"
            with self.subTest(key=key):
                with self.assertRaisesRegex(CurrentProductionFinalAcceptanceError,"SESSION_GUARDS_NOT_PASS"):
                    self.validate(s=s)

    def test_scheduler_determinism_freeze_are_independent_gates(self):
        sch=scheduler(); sch["missed_execution_count"]=1
        with self.assertRaisesRegex(CurrentProductionFinalAcceptanceError,"SCHEDULER_NOT_PASS"):
            self.validate(sch=sch)
        sch=scheduler(); sch["actual_timing_evidence"]="FAIL"
        with self.assertRaisesRegex(CurrentProductionFinalAcceptanceError,"SCHEDULER_NOT_PASS"):
            self.validate(sch=sch)
        d=deterministic(); d["deterministic_audit_replay"]="FAIL"
        with self.assertRaisesRegex(CurrentProductionFinalAcceptanceError,"DETERMINISTIC_NOT_PASS"):
            self.validate(d=d)
        f=freeze(); f["model_freeze_integrity"]="FAIL"
        with self.assertRaisesRegex(CurrentProductionFinalAcceptanceError,"MODEL_FREEZE_NOT_PASS"):
            self.validate(f=f)

    def test_cross_main_evidence_is_rejected(self):
        s=session(); s["merged_main_sha"]="b"*40
        with self.assertRaisesRegex(CurrentProductionFinalAcceptanceError,"SESSION_MAIN_MISMATCH"):
            self.validate(s=s)


    def test_route_b_final_acceptance_requires_activation_binding(self):
        p=post_route_b()
        s=session()
        s["activation_code_sha"]=MAIN
        s["activation_binding_sha"]=BIND
        s["operational_head_policy"]="AUTHORIZED_DESCENDANT_POINTER_COMMITS_ONLY"
        result=self.validate(p=p,s=s)
        self.assertEqual(result["route"],"B_ZERO_FEE")
        self.assertEqual(result["activation_code_sha"],MAIN)
        self.assertEqual(result["operational_head_policy"],"AUTHORIZED_DESCENDANT_POINTER_COMMITS_ONLY")

    def test_route_b_wrong_session_activation_code_rejected(self):
        p=post_route_b()
        s=session()
        s["activation_code_sha"]="b"*40
        s["activation_binding_sha"]=BIND
        s["operational_head_policy"]="AUTHORIZED_DESCENDANT_POINTER_COMMITS_ONLY"
        with self.assertRaisesRegex(CurrentProductionFinalAcceptanceError,"SESSION_ACTIVATION_CODE_MISMATCH"):
            self.validate(p=p,s=s)

    def test_route_b_wrong_operational_policy_rejected(self):
        p=post_route_b()
        s=session()
        s["activation_code_sha"]=MAIN
        s["operational_head_policy"]="EXACT_MERGED_MAIN_ONLY"
        with self.assertRaisesRegex(CurrentProductionFinalAcceptanceError,"SESSION_OPERATIONAL_POLICY_INVALID"):
            self.validate(p=p,s=s)

if __name__=="__main__":
    unittest.main()

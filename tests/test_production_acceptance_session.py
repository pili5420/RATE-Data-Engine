from __future__ import annotations
import unittest

from src.production_acceptance_session import (
    ProductionAcceptanceSessionError,
    admit_scheduled_run,
    open_production_acceptance_session,
    summarize_production_acceptance_session,
)

MAIN="a"*40

def post_merge():
    return {
        "artifact":"RATE_POST_MERGE_PRODUCTION_ACTIVATION_VERIFICATION_V1",
        "validation_status":"PASS",
        "final_disposition":"PRODUCTION_ACTIVATION_VERIFIED",
        "merged_main_sha":MAIN,
        "production_credit":1,
        "cer081_credit":0,
    }

def run(day,cadence,run_id):
    return {
        "event":"schedule",
        "validation_status":"PASS",
        "publish_result":"PASS",
        "trading_date":day,
        "cadence":cadence,
        "run_head_sha":MAIN,
        "workflow_run_id":run_id,
        "workflow_job_id":run_id+1000,
        "fallback_used":False,
        "automatic_retry_count":0,
        "production_data_gate":"PASS",
        "decision_state_continuity":True,
        "portfolio_continuity":True,
        "transaction_ledger_continuity":True,
        "ranking_model_continuity":True,
        "current_state_id":f"state-{run_id}",
        "previous_state_id":f"state-{run_id-1}",
        "production_snapshot_id":f"snapshot-{run_id}",
        "input_snapshot_id":f"input-{run_id}",
    }

class SessionTests(unittest.TestCase):
    def test_activation_required_to_open(self):
        bad=post_merge(); bad["final_disposition"]="BLOCKED"
        with self.assertRaisesRegex(ProductionAcceptanceSessionError,"ACTIVATION_NOT_VERIFIED"):
            open_production_acceptance_session(bad,session_start_date="2026-11-05")

    def test_pre_session_history_is_rejected(self):
        s=open_production_acceptance_session(post_merge(),session_start_date="2026-11-05")
        with self.assertRaisesRegex(ProductionAcceptanceSessionError,"PRE_SESSION_HISTORY_FORBIDDEN"):
            admit_scheduled_run(s,run("2026-11-04","07:30",1))

    def test_manual_dispatch_and_cross_main_are_rejected(self):
        s=open_production_acceptance_session(post_merge(),session_start_date="2026-11-05")
        r=run("2026-11-05","07:30",1); r["event"]="workflow_dispatch"
        with self.assertRaisesRegex(ProductionAcceptanceSessionError,"NOT_OFFICIAL_SCHEDULE"):
            admit_scheduled_run(s,r)
        r=run("2026-11-05","07:30",1); r["run_head_sha"]="b"*40
        with self.assertRaisesRegex(ProductionAcceptanceSessionError,"MAIN_BINDING_MISMATCH"):
            admit_scheduled_run(s,r)

    def test_duplicate_is_fail_closed(self):
        s=open_production_acceptance_session(post_merge(),session_start_date="2026-11-05")
        r=run("2026-11-05","07:30",1)
        s=admit_scheduled_run(s,r)
        with self.assertRaisesRegex(ProductionAcceptanceSessionError,"DUPLICATE_FORBIDDEN"):
            admit_scheduled_run(s,r)

    def test_three_complete_days_twelve_runs_becomes_ready(self):
        s=open_production_acceptance_session(post_merge(),session_start_date="2026-11-05")
        rid=1
        for day in ("2026-11-05","2026-11-06","2026-11-09"):
            for cadence in ("07:30","09:30","12:00","19:30"):
                s=admit_scheduled_run(s,run(day,cadence,rid))
                rid+=1
        self.assertEqual(s["completion_status"],"READY_FOR_FINAL_ACCEPTANCE")
        summary=summarize_production_acceptance_session(s)
        self.assertEqual(summary["trading_days_tested"],3)
        self.assertEqual(summary["successful_cadence_runs"],12)
        self.assertEqual(summary["full_4_cadence_scheduled_coverage"],"PASS")
        self.assertEqual(summary["completion_status"],"READY_FOR_CER081_FINAL_ACCEPTANCE")
        self.assertFalse(summary["production_acceptance_granted"])
        self.assertEqual(summary["cer081_credit"],0)

if __name__=="__main__":
    unittest.main()

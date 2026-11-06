from __future__ import annotations

from datetime import timedelta
from unittest.mock import patch
import unittest

from src.cer081_scheduler_actual_timing import (
    CADENCE_CRONS, CADENCE_WORKFLOWS, build_actual_timing_evidence, expected_slot_utc,
)
from src.intraday_activation_candidate_review import canonical_digest
from src.production_acceptance_session import summarize_production_acceptance_session
from src.route_b_current_production_finalization import build_finalization

CODE="a"*40
BIND="d"*40

def activation():
    return {
        "artifact":"RATE_POST_MERGE_PRODUCTION_ACTIVATION_VERIFICATION_V1",
        "validation_status":"PASS","final_disposition":"PRODUCTION_ACTIVATION_VERIFIED",
        "route":"B_ZERO_FEE","merged_main_sha":CODE,
        "activation_code_sha":CODE,"activation_binding_sha":BIND,
        "operational_head_policy":"AUTHORIZED_DESCENDANT_POINTER_COMMITS_ONLY",
        "production_credit":1,"cer081_credit":0
    }

def session():
    runs=[]; rid=1; previous="seed"
    for day in ("2026-11-06","2026-11-09","2026-11-10"):
        for cadence in ("07:30","09:30","12:00","19:30"):
            current=f"s{rid}"
            runs.append({"trading_date":day,"cadence":cadence,
                         "workflow_run_id":str(rid),"workflow_job_id":str(100+rid),
                         "run_head_sha":("b"*39)+hex(rid%16)[2:],
                         "activation_code_sha":CODE,"activation_binding_sha":BIND,
                         "current_state_id":current,"previous_state_id":previous,
                         "production_snapshot_id":f"p{rid}","input_snapshot_id":f"i{rid}",
                         "official_event":"schedule","production_data_gate":"PASS",
                         "decision_state_continuity":True,"portfolio_continuity":True,
                         "transaction_ledger_continuity":True,"ranking_model_continuity":"PASS",
                         "fallback_used":False,"automatic_retry_count":0})
            # Synthetic fixtures, never Production evidence.
            slot=expected_slot_utc(day,cadence)
            row=runs[-1]
            row["scheduler_actual_timing"]=build_actual_timing_evidence(
                {"id":rid,"event":"schedule","path":CADENCE_WORKFLOWS[cadence],
                 "head_sha":row["run_head_sha"],"run_attempt":1,
                 "created_at":(slot+timedelta(seconds=60)).isoformat(),
                 "run_started_at":(slot+timedelta(seconds=120)).isoformat()},
                cadence=cadence,trading_date=day,event_schedule=CADENCE_CRONS[cadence],
                workflow_path=CADENCE_WORKFLOWS[cadence],expected_run_id=str(rid),
                expected_head_sha=row["run_head_sha"])
            row["scheduler_timing_provenance"]={"synthetic_source_verified":True}
            previous=current; rid+=1
    return {
        "artifact":"RATE_V11_PRODUCTION_ACCEPTANCE_SESSION_V1",
        "validation_status":"PASS","governance_scope":"CURRENT_PRODUCTION",
        "merged_main_sha":CODE,"activation_code_sha":CODE,"activation_binding_sha":BIND,
        "operational_head_policy":"AUTHORIZED_DESCENDANT_POINTER_COMMITS_ONLY",
        "session_start_date":"2026-11-06","required_trading_days":3,
        "required_scheduled_runs":12,"required_cadences":["07:30","09:30","12:00","19:30"],
        "official_event_required":"schedule","manual_dispatch_credit_allowed":False,
        "historical_pre_activation_credit_allowed":False,"cross_main_credit_allowed":False,
        "duplicate_run_credit_allowed":False,"fallback_allowed":False,
        "automatic_recovery_credit_allowed":False,"accepted_runs":runs,
        "trading_days_tested":3,"successful_cadence_runs":12,"missing_cadence_runs":0,
        "duplicate_cadence_runs":0,"completion_status":"READY_FOR_FINAL_ACCEPTANCE",
        "production_acceptance_granted":False,"cer081_credit":0
    }

class FinalizationTests(unittest.TestCase):
    def build_from_synthetic_session(self,s):
        with patch("src.route_b_current_production_finalization.load_live_state") as load, \
                patch("src.route_b_current_production_finalization.build_ancestry_evidence") as ancestry, \
                patch("src.route_b_current_production_finalization.verify_timing_provenance",
                      return_value={"synthetic_source_verified":True}):
            by_slot={(r["trading_date"],r["cadence"]):r for r in s["accepted_runs"]}
            def loader(root,day,cadence):
                r=by_slot[(day,cadence)]
                return {"state":{"current_state_id":r["current_state_id"],
                                 "previous_state_id":r["previous_state_id"],
                                 "decision_payload_hash":"f"*64},
                        "manifest":{"workflow_run_id":r["workflow_run_id"],
                                    "commit_sha":r["run_head_sha"],"event_name":"schedule"}}
            load.side_effect=loader
            ancestry.return_value={"validation_status":"PASS"}
            return build_finalization(".", "artifacts",activation=activation(),session=s,
                                      session_summary=summarize_production_acceptance_session(s))

    def test_full_pass(self):
        out=self.build_from_synthetic_session(session())
        self.assertEqual(out["final_disposition"],"RATE_V11_PRODUCTION_ACCEPTED")
        self.assertEqual(out["cer081_status"],"CER081_ACCEPTED_CLOSED")
        self.assertEqual(out["scheduler_reliability_summary"]["successful_cadence_runs"],12)
        self.assertEqual(out["scheduler_reliability_summary"]["actual_timing_evidence_count"],12)
        self.assertEqual(out["scheduler_reliability_summary"]["max_scheduler_delay_seconds"],120)
        self.assertEqual(out["scheduler_reliability_summary"]["delayed_execution_blocking_count"],0)
        self.assertEqual(len(out["github_actions_provenance_replay"]),12)
        self.assertEqual(out["deterministic_replay_summary"]["replay_new_record_count"],0)
        self.assertEqual(out["model_freeze_summary"]["unreviewed_code_change_count"],0)

    def test_missing_actual_timing_fails_closed(self):
        s=session()
        s["accepted_runs"][0].pop("scheduler_actual_timing")
        with self.assertRaisesRegex(Exception,"ROUTE_B_FINAL_SCHEDULER_ACTUAL_TIMING_NOT_PASS"):
            self.build_from_synthetic_session(s)

    def test_delayed_execution_never_reports_zero(self):
        s=session()
        s["accepted_runs"][0]["scheduler_actual_timing"]["scheduler_start_delay_seconds"]=901
        with self.assertRaisesRegex(Exception,"ROUTE_B_FINAL_SCHEDULER_ACTUAL_TIMING_NOT_PASS"):
            self.build_from_synthetic_session(s)

    def test_replayed_receipt_mismatch_fails_closed(self):
        s=session()
        s["accepted_runs"][0]["scheduler_timing_provenance"]={"fabricated_hash":"0"*64}
        with self.assertRaisesRegex(Exception,"ORIGINAL_TIMING_PROVENANCE_MISMATCH"):
            self.build_from_synthetic_session(s)

    def test_pre_session_history_rejected_before_replay(self):
        s=session()
        s["session_start_date"]="2026-11-09"
        with self.assertRaisesRegex(Exception,"PRE_SESSION_HISTORY_FORBIDDEN"):
            self.build_from_synthetic_session(s)

    def test_not_ready_rejected(self):
        s=session(); s["accepted_runs"]=s["accepted_runs"][:8]
        s["successful_cadence_runs"]=8; s["trading_days_tested"]=2; s["missing_cadence_runs"]=4
        summary=summarize_production_acceptance_session(s)
        with self.assertRaisesRegex(Exception,"SESSION_NOT_READY"):
            build_finalization(".", "artifacts",activation=activation(),session=s,session_summary=summary)

if __name__=="__main__":
    unittest.main()

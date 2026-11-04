from __future__ import annotations

from unittest.mock import patch
import tempfile
import unittest

from src.route_b_acceptance_collector import collect_scheduled_run
from src.route_b_acceptance_store import persist_activation_package

MAIN="a"*40

def package():
    return {
        "artifact":"RATE_ROUTE_B_ACTIVATION_RUNTIME_PACKAGE_V1",
        "validation_status":"PASS","runtime_mode":"ACTIVE",
        "activation":{"artifact":"RATE_POST_MERGE_PRODUCTION_ACTIVATION_VERIFICATION_V1",
                      "final_disposition":"PRODUCTION_ACTIVATION_VERIFIED"},
        "session":{
            "artifact":"RATE_V11_PRODUCTION_ACCEPTANCE_SESSION_V1",
            "validation_status":"PASS","governance_scope":"CURRENT_PRODUCTION",
            "merged_main_sha":MAIN,"activation_code_sha":MAIN,
            "operational_head_policy":"AUTHORIZED_DESCENDANT_POINTER_COMMITS_ONLY",
            "session_start_date":"2026-11-06","required_trading_days":3,
            "required_scheduled_runs":12,"required_cadences":["07:30","09:30","12:00","19:30"],
            "official_event_required":"schedule","manual_dispatch_credit_allowed":False,
            "historical_pre_activation_credit_allowed":False,"cross_main_credit_allowed":False,
            "duplicate_run_credit_allowed":False,"fallback_allowed":False,
            "automatic_recovery_credit_allowed":False,"accepted_runs":[],
            "trading_days_tested":0,"successful_cadence_runs":0,
            "missing_cadence_runs":12,"duplicate_cadence_runs":0,
            "completion_status":"IN_PROGRESS","production_acceptance_granted":False,"cer081_credit":0
        }
    }

class CollectorTests(unittest.TestCase):
    @patch("src.route_b_acceptance_collector.baseline_policy")
    def test_pending_is_noop(self,policy):
        policy.return_value={"status":"PENDING_BINDING"}
        out=collect_scheduled_run(".","artifacts","source","store",cadence="09:30",source_run_id="1")
        self.assertEqual(out["collector_result"],"NOOP_PENDING_BASELINE_BINDING")

    @patch("src.route_b_acceptance_collector.baseline_policy")
    def test_missing_session_is_noop(self,policy):
        policy.return_value={"status":"ACTIVE"}
        with tempfile.TemporaryDirectory() as d:
            out=collect_scheduled_run(".","artifacts","source",d,cadence="09:30",source_run_id="1")
            self.assertEqual(out["collector_result"],"NOOP_WAITING_FOR_ACTIVATION_SESSION")

    @patch("src.route_b_acceptance_collector.baseline_policy")
    @patch("src.route_b_acceptance_collector._find_slot")
    @patch("src.route_b_acceptance_collector.load_live_state")
    @patch("src.route_b_acceptance_collector.build_ancestry_evidence")
    @patch("src.route_b_acceptance_collector.validate_overlay")
    @patch("src.route_b_acceptance_collector.bind_overlay_run_to_session")
    def test_overlay_cadence_admission(self,bind,overlay,ancestry,load,find,policy):
        policy.return_value={"status":"ACTIVE"}
        find.return_value=("2026-11-06",{"event_name":"schedule","workflow_run_id":"7","commit_sha":"b"*40})
        load.side_effect=[{"state":{"current_state_id":"cur","decision":{}}},
                          {"state":{"current_state_id":"prev","decision":{}}}]
        ancestry.return_value={"validation_status":"PASS","source_heads":{"09:30":{"source_head_sha":"b"*40}}}
        overlay.return_value={"artifact":"RATE_ROUTE_B_PRODUCTION_CHECKPOINT_ACCEPTANCE_V1"}
        bind.return_value={
            "event":"schedule","validation_status":"PASS","publish_result":"PASS",
            "trading_date":"2026-11-06","cadence":"09:30","run_head_sha":"b"*40,
            "activation_code_sha":MAIN,"activation_is_ancestor":True,
            "operational_changes_authorized":True,"workflow_run_id":"7",
            "fallback_used":False,"automatic_retry_count":0,"production_data_gate":"PASS",
            "decision_state_continuity":True,"portfolio_continuity":True,
            "transaction_ledger_continuity":True,"ranking_model_continuity":True,
            "current_state_id":"cur","previous_state_id":"prev"
        }
        with tempfile.TemporaryDirectory() as d:
            persist_activation_package(package(),d)
            out=collect_scheduled_run(".","artifacts","source",d,cadence="09:30",source_run_id="7")
            self.assertEqual(out["collector_result"],"RUN_ADMITTED")
            self.assertTrue(out["session_written"])

if __name__=="__main__":
    unittest.main()

from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch
import tempfile
import unittest

from src.cer081_scheduler_actual_timing import (
    CADENCE_CRONS, CADENCE_WORKFLOWS, build_actual_timing_evidence, expected_slot_utc,
)
from src.route_b_acceptance_collector import collect_scheduled_run, _phase2_standard_run
from src.route_b_acceptance_store import persist_activation_package

MAIN="a"*40
BIND="d"*40

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
            "activation_binding_sha":BIND,
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
        ancestry.return_value={"validation_status":"PASS","source_heads":{"09:30":{"source_head_sha":"b"*40,"activation_is_ancestor":True,"binding_is_ancestor":True,"changed_paths_since_activation":[]}}}
        overlay.return_value={"artifact":"RATE_ROUTE_B_PRODUCTION_CHECKPOINT_ACCEPTANCE_V1"}
        bind.return_value={
            "event":"schedule","validation_status":"PASS","publish_result":"PASS",
            "trading_date":"2026-11-06","cadence":"09:30","run_head_sha":"b"*40,
            "activation_code_sha":MAIN,"activation_binding_sha":BIND,"activation_is_ancestor":True,
            "operational_changes_authorized":True,"workflow_run_id":"7",
            "fallback_used":False,"automatic_retry_count":0,"production_data_gate":"PASS",
            "decision_state_continuity":True,"portfolio_continuity":True,
            "transaction_ledger_continuity":True,"ranking_model_continuity":True,
            "current_state_id":"cur","previous_state_id":"prev"
        }
        from src.route_b_acceptance_store import load_session
        for delay in (120,900,900.9):
            with self.subTest(delay=delay), tempfile.TemporaryDirectory() as d:
                load.side_effect=[{"state":{"current_state_id":"cur","decision":{}}},
                                  {"state":{"current_state_id":"prev","decision":{}}}]
                slot=expected_slot_utc("2026-11-06","09:30")
                timing=build_actual_timing_evidence(
                    {"id":7,"event":"schedule","path":CADENCE_WORKFLOWS["09:30"],
                     "head_sha":"b"*40,"run_attempt":1,
                     "created_at":(slot+timedelta(seconds=60)).isoformat(),
                     "run_started_at":(slot+timedelta(seconds=delay)).isoformat()},
                    cadence="09:30",trading_date="2026-11-06",
                    event_schedule=CADENCE_CRONS["09:30"],
                    workflow_path=CADENCE_WORKFLOWS["09:30"],
                    expected_run_id="7",expected_head_sha="b"*40)
                source=Path(d)/"source"
                source.mkdir()
                (source/"RATE_CER081_SCHEDULER_ACTUAL_TIMING_EVIDENCE.json").write_text(
                    json.dumps(timing),encoding="utf-8")
                persist_activation_package(package(),d)
                if delay > 900:
                    with self.assertRaisesRegex(RuntimeError,"SCHEDULER_BLOCKING_DELAY"):
                        collect_scheduled_run(".","artifacts",source,d,
                                              cadence="09:30",source_run_id="7")
                    self.assertEqual(load_session(d)["accepted_runs"],[])
                    continue
                out=collect_scheduled_run(".","artifacts",source,d,
                                          cadence="09:30",source_run_id="7")
                self.assertEqual(out["collector_result"],"RUN_ADMITTED")
                self.assertTrue(out["session_written"])
                accepted=load_session(d)["accepted_runs"]
                self.assertEqual(accepted[0]["scheduler_actual_timing"],timing)


    @patch("src.route_b_acceptance_collector.validate_phase2_transition")
    @patch("src.route_b_acceptance_collector._read_unique")
    def test_phase2_0730_evidence_admission(self,read_unique,validate_transition):
        current={"current_state_id":"cur","decision_payload_hash":"hcur",
                 "previous_state_id":"prev","decision":{
                    "phase2":True,"validation_status":"PASS","fallback_used":False,
                    "trading_date":"2026-11-06","cadence":"07:30",
                    "previous_state_id":"prev","previous_state_hash":"hprev",
                    "full_market_refresh":False,"runtime_mode":"CONSUME_LATEST_PASS_1930",
                    "records":[{"symbol":"2330"}],"top50":["a"],"short_top30":["b"],"long_top30":["c"],
                    "roy_portfolio":{"x":1},"ai_paper_portfolio":{"x":2},
                    "transaction_ledger":{"transactions":[]},
                    "production_snapshot_id":"ps","input_snapshot_id":"is"}}
        previous={"current_state_id":"prev","decision_payload_hash":"hprev",
                  "decision":{"records":[{"symbol":"2330"}],"top50":["a"],"short_top30":["b"],"long_top30":["c"],
                              "roy_portfolio":{"x":1},"ai_paper_portfolio":{"x":2},
                              "transaction_ledger":{"transactions":[]}}}
        runtime={"validation_status":"PASS","current_state_id":"cur","current_state_hash":"hcur","fallback_used":False}
        ingestion={"validation_status":"PASS","proposed_state_id":"cur","fallback_used":False,"blocked_dependencies":[]}
        live={"validation_status":"PASS","live_state_updated":True,"current_state_id":"cur","current_state_hash":"hcur"}
        read_unique.side_effect=[runtime,ingestion,live]
        manifest={"commit_sha":"b"*40,"workflow_run_id":"7","workflow_job_id":"8"}
        run=_phase2_standard_run(current,previous,manifest,"source","state-root","07:30")
        self.assertEqual(run["production_data_gate"],"PASS")
        self.assertEqual(run["route_b_standard_runtime"],"PHASE2_DYNAMIC")
        validate_transition.assert_called_once()

    @patch("src.route_b_acceptance_collector.validate_phase2_transition")
    @patch("src.route_b_acceptance_collector._read_unique")
    def test_phase2_1930_requires_full_market_refresh(self,read_unique,validate_transition):
        current={"current_state_id":"cur","decision_payload_hash":"hcur",
                 "previous_state_id":"prev","decision":{
                    "phase2":True,"validation_status":"PASS","fallback_used":False,
                    "trading_date":"2026-11-06","cadence":"19:30",
                    "previous_state_id":"prev","previous_state_hash":"hprev",
                    "full_market_refresh":False,"runtime_mode":"FULL_MARKET_REFRESH",
                    "top50":["a"]*50,"short_top30":["b"]*30,"long_top30":["c"]*30,
                    "roy_portfolio":{"x":1},"ai_paper_portfolio":{"x":2},
                    "transaction_ledger":{"transactions":[]}}}
        previous={"current_state_id":"prev","decision_payload_hash":"hprev","decision":{}}
        read_unique.side_effect=[
            {"validation_status":"PASS","current_state_id":"cur","current_state_hash":"hcur","fallback_used":False},
            {"validation_status":"PASS","proposed_state_id":"cur","fallback_used":False,"blocked_dependencies":[]},
            {"validation_status":"PASS","live_state_updated":True,"current_state_id":"cur","current_state_hash":"hcur"},
        ]
        with self.assertRaisesRegex(Exception,"1930_PHASE2_FULL_MARKET_INVALID"):
            _phase2_standard_run(current,previous,{"commit_sha":"b"*40},"source","state-root","19:30")

if __name__=="__main__":
    unittest.main()

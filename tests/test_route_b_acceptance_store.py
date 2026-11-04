from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from src.route_b_acceptance_store import (
    RouteBAcceptanceStoreError,
    admit_run_to_store,
    load_session,
    persist_activation_package,
)

MAIN="a"*40

def package():
    session={
        "artifact":"RATE_V11_PRODUCTION_ACCEPTANCE_SESSION_V1",
        "validation_status":"PASS","governance_scope":"CURRENT_PRODUCTION",
        "merged_main_sha":MAIN,"activation_code_sha":MAIN,
        "operational_head_policy":"AUTHORIZED_DESCENDANT_POINTER_COMMITS_ONLY",
        "session_start_date":"2026-11-06",
        "required_trading_days":3,"required_scheduled_runs":12,
        "required_cadences":["07:30","09:30","12:00","19:30"],
        "official_event_required":"schedule","manual_dispatch_credit_allowed":False,
        "historical_pre_activation_credit_allowed":False,"cross_main_credit_allowed":False,
        "duplicate_run_credit_allowed":False,"fallback_allowed":False,
        "automatic_recovery_credit_allowed":False,"accepted_runs":[],
        "trading_days_tested":0,"successful_cadence_runs":0,
        "missing_cadence_runs":12,"duplicate_cadence_runs":0,
        "completion_status":"IN_PROGRESS","production_acceptance_granted":False,
        "cer081_credit":0
    }
    return {
        "artifact":"RATE_ROUTE_B_ACTIVATION_RUNTIME_PACKAGE_V1",
        "validation_status":"PASS","runtime_mode":"ACTIVE",
        "activation":{"artifact":"RATE_POST_MERGE_PRODUCTION_ACTIVATION_VERIFICATION_V1",
                      "final_disposition":"PRODUCTION_ACTIVATION_VERIFIED"},
        "session":session,
    }

def run(run_id="1",state="s1",head="b"*40):
    return {
        "event":"schedule","validation_status":"PASS","publish_result":"PASS",
        "trading_date":"2026-11-06","cadence":"07:30",
        "run_head_sha":head,"activation_code_sha":MAIN,
        "activation_is_ancestor":True,"operational_changes_authorized":True,
        "workflow_run_id":run_id,"workflow_job_id":"10",
        "fallback_used":False,"automatic_retry_count":0,
        "production_data_gate":"PASS","decision_state_continuity":True,
        "portfolio_continuity":True,"transaction_ledger_continuity":True,
        "ranking_model_continuity":True,"current_state_id":state,
        "previous_state_id":"prior"
    }

class StoreTests(unittest.TestCase):
    def test_create_and_idempotent_package(self):
        with tempfile.TemporaryDirectory() as d:
            first=persist_activation_package(package(),d)
            second=persist_activation_package(package(),d)
            self.assertEqual(first["store_result"],"SESSION_CREATED")
            self.assertEqual(second["store_result"],"IDEMPOTENT_NOOP_EXISTING_SESSION")
            self.assertEqual(load_session(d)["successful_cadence_runs"],0)

    def test_admit_and_idempotent_run(self):
        with tempfile.TemporaryDirectory() as d:
            persist_activation_package(package(),d)
            first=admit_run_to_store(d,run())
            second=admit_run_to_store(d,run())
            self.assertEqual(first["store_result"],"RUN_ADMITTED")
            self.assertEqual(second["store_result"],"IDEMPOTENT_NOOP_EXISTING_RUN")

    def test_conflicting_duplicate_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            persist_activation_package(package(),d)
            admit_run_to_store(d,run())
            with self.assertRaisesRegex(RouteBAcceptanceStoreError,"CONFLICTING_DUPLICATE_RUN"):
                admit_run_to_store(d,run(state="different"))

    def test_pre_session_run_is_noop(self):
        with tempfile.TemporaryDirectory() as d:
            persist_activation_package(package(),d)
            r=run(); r["trading_date"]="2026-11-05"
            out=admit_run_to_store(d,r)
            self.assertEqual(out["store_result"],"NOOP_PRE_SESSION_RUN")
            self.assertEqual(load_session(d)["successful_cadence_runs"],0)

if __name__=="__main__":
    unittest.main()

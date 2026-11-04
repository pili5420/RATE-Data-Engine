from __future__ import annotations

import unittest

from src.production_acceptance_session import admit_scheduled_run
from src.route_b_acceptance_bridge import (
    RouteBAcceptanceBridgeError,
    bind_overlay_run_to_session,
    bind_standard_run_to_session,
    build_activation_and_open_session,
)

BASE="a"*40
H0930="b"*40
H1200="c"*40

def overlay(cadence,head,state,previous):
    return {
        "artifact":"RATE_ROUTE_B_PRODUCTION_CHECKPOINT_ACCEPTANCE_V1",
        "validation_status":"PASS","route":"B_ZERO_FEE",
        "source_workflow_run_id":"101" if cadence=="09:30" else "102",
        "source_workflow_job_id":"201" if cadence=="09:30" else "202",
        "source_event_name":"schedule","source_head_sha":head,
        "trading_date":"2026-11-05","cadence":cadence,
        "source_state_id":state,"source_state_hash":"d"*64,
        "previous_state_id":previous,
        "official_public_evidence_gate":"PASS",
        "current_intraday_price":None,"current_intraday_volume":None,
        "intraday_rerank_performed":False,"paper_trade_fill_count":0,
        "production_data_gate":"PASS","decision_state_continuity":True,
        "portfolio_continuity":True,"transaction_ledger_continuity":True,
        "ranking_model_continuity":True,"fallback_used":False,
        "automatic_retry_count":0,"scheduled_soak_credit":True,
        "production_acceptance_eligible":True,"cer081_credit":0,
        "canonical_state_mutated":False
    }

def ancestry():
    return {
        "artifact":"RATE_ROUTE_B_GIT_ANCESTRY_EVIDENCE_V1",
        "validation_status":"PASS",
        "activation_merge_sha":BASE,
        "source_heads":{
            "09:30":{"source_head_sha":H0930,"activation_is_ancestor":True,
                     "changed_paths_since_activation":["artifacts/production_state/live/2026-11-05/0930/x.json"]},
            "12:00":{"source_head_sha":H1200,"activation_is_ancestor":True,
                     "changed_paths_since_activation":["artifacts/RATE_PRODUCTION_STATE_LATEST.json"]}
        }
    }

class BridgeTests(unittest.TestCase):
    def test_activation_opens_on_next_trading_day(self):
        a=overlay("09:30",H0930,"s0930","s0730")
        b=overlay("12:00",H1200,"s1200","s0930")
        out=build_activation_and_open_session(a,b,ancestry(),activation_merge_sha=BASE)
        self.assertEqual(out["activation"]["final_disposition"],"PRODUCTION_ACTIVATION_VERIFIED")
        self.assertEqual(out["session"]["activation_code_sha"],BASE)
        self.assertEqual(out["session_start_date"],"2026-11-06")
        self.assertFalse(out["activation_day_acceptance_credit_allowed"])

    def test_friday_activation_skips_weekend(self):
        a=overlay("09:30",H0930,"s0930","s0730"); a["trading_date"]="2026-11-06"
        b=overlay("12:00",H1200,"s1200","s0930"); b["trading_date"]="2026-11-06"
        out=build_activation_and_open_session(a,b,ancestry(),activation_merge_sha=BASE)
        self.assertEqual(out["session_start_date"],"2026-11-09")

    def test_overlay_run_binds_to_session_and_can_be_admitted(self):
        a=overlay("09:30",H0930,"s0930","s0730")
        b=overlay("12:00",H1200,"s1200","s0930")
        bridge=build_activation_and_open_session(a,b,ancestry(),activation_merge_sha=BASE)
        session=bridge["session"]
        future=overlay("09:30","e"*40,"x0930","x0730")
        future["trading_date"]=session["session_start_date"]
        row={"source_head_sha":"e"*40,"activation_is_ancestor":True,
             "changed_paths_since_activation":["artifacts/RATE_PRODUCTION_STATE_LATEST.json"]}
        run=bind_overlay_run_to_session(future,session,row)
        out=admit_scheduled_run(session,run)
        self.assertEqual(out["successful_cadence_runs"],1)

    def test_unauthorized_overlay_change_is_rejected(self):
        a=overlay("09:30",H0930,"s0930","s0730")
        b=overlay("12:00",H1200,"s1200","s0930")
        session=build_activation_and_open_session(a,b,ancestry(),activation_merge_sha=BASE)["session"]
        future=overlay("09:30","e"*40,"x0930","x0730")
        future["trading_date"]=session["session_start_date"]
        row={"source_head_sha":"e"*40,"activation_is_ancestor":True,
             "changed_paths_since_activation":["src/rate_logic.py"]}
        with self.assertRaisesRegex(RouteBAcceptanceBridgeError,"UNAUTHORIZED_OPERATIONAL_CHANGE"):
            bind_overlay_run_to_session(future,session,row)

    def test_standard_0730_1930_binding(self):
        a=overlay("09:30",H0930,"s0930","s0730")
        b=overlay("12:00",H1200,"s1200","s0930")
        session=build_activation_and_open_session(a,b,ancestry(),activation_merge_sha=BASE)["session"]
        standard={
            "event":"schedule","validation_status":"PASS","publish_result":"PASS",
            "trading_date":session["session_start_date"],"cadence":"07:30",
            "run_head_sha":"f"*40,"fallback_used":False,"automatic_retry_count":0,
            "production_data_gate":"PASS","decision_state_continuity":True,
            "portfolio_continuity":True,"transaction_ledger_continuity":True,
            "ranking_model_continuity":True,"current_state_id":"s0730",
            "previous_state_id":"prior1930"
        }
        row={"source_head_sha":"f"*40,"activation_is_ancestor":True,
             "changed_paths_since_activation":["artifacts/production_state/live/2026-11-06/0730/x.json"]}
        normalized=bind_standard_run_to_session(standard,session,row)
        self.assertEqual(normalized["activation_code_sha"],BASE)
        self.assertTrue(normalized["operational_changes_authorized"])

if __name__=="__main__":
    unittest.main()

from __future__ import annotations
from copy import deepcopy
import unittest
from src.cer074_acceptance import sha256, strip_runtime
from src.route_b_acceptance_overlay import RouteBOverlayError, validate_overlay

DAY="2026-11-05"

def base_state():
    decision={
        "execution_scope":"PRODUCTION","trading_date":DAY,"cadence":"07:30",
        "previous_state_resolution":"PERSISTED_PRODUCTION_STATE","previous_state_id":"prior",
        "records":[{"symbol":"2330","score":1}],
        "top50":["2330"],"short_top30":["2330"],"long_top30":["2330"],
        "roy_portfolio":{"positions":[]},
        "ai_paper_portfolio":{"positions":[],"cash":1000000,"nav":1000000,"reset":False},
        "transaction_ledger":{"transactions":[],"reset":False},
        "model_learning_state":{"v":1}
    }
    h=sha256(strip_runtime(decision))
    return {"current_state_id":"rate-state-"+h[:24],"decision_payload_hash":h,"decision":decision}

def partial(previous,cadence):
    prior=previous["decision"]
    decision=deepcopy(prior)
    decision.update({
        "trading_date":DAY,"cadence":cadence,
        "previous_state_resolution":"PERSISTED_PRODUCTION_STATE",
        "previous_state_id":previous["current_state_id"],
        "previous_state_hash":previous["decision_payload_hash"],
        "report_runtime_status":"PARTIAL_VALID",
        "public_official_evidence_gate":"PASS",
        "fallback_allowed":False,
        "previous_state_records":deepcopy(prior["records"]),
        "records":[{"symbol":"2330","current_price":None,"current_volume":None}]
    })
    h=sha256(strip_runtime(decision))
    return {"current_state_id":"rate-state-"+h[:24],"decision_payload_hash":h,
            "previous_state_id":previous["current_state_id"],"decision":decision}

def manifest(cadence):
    return {"validation_status":"PASS","event_name":"schedule","workflow_run_id":"101",
            "commit_sha":"a"*40,"trading_date":DAY,"cadence":cadence}

class OverlayTests(unittest.TestCase):
    def test_0930_pass(self):
        p=base_state(); s=partial(p,"09:30")
        r=validate_overlay(s,p,manifest("09:30"),source_run_id="101")
        self.assertEqual(r["production_data_gate"],"PASS")
        self.assertTrue(r["scheduled_soak_credit"])
        self.assertFalse(r["canonical_state_mutated"])

    def test_1200_pass(self):
        p=base_state(); morning=partial(p,"09:30"); noon=partial(morning,"12:00")
        r=validate_overlay(noon,morning,manifest("12:00"),source_run_id="101")
        self.assertTrue(r["decision_state_continuity"])

    def test_non_schedule_rejected(self):
        p=base_state(); s=partial(p,"09:30"); m=manifest("09:30"); m["event_name"]="manual"
        with self.assertRaisesRegex(RouteBOverlayError,"SOURCE_EVENT_INVALID"):
            validate_overlay(s,p,m,source_run_id="101")

    def test_market_value_rejected(self):
        p=base_state(); s=partial(p,"09:30"); s["decision"]["records"][0]["current_price"]=100
        with self.assertRaisesRegex(RouteBOverlayError,"CURRENT_MARKET_VALUE_INVALID"):
            validate_overlay(s,p,manifest("09:30"),source_run_id="101")

    def test_ledger_tamper_rejected(self):
        p=base_state(); s=partial(p,"09:30")
        s["decision"]["transaction_ledger"]={"transactions":[{"id":"x"}],"reset":False}
        with self.assertRaisesRegex(RouteBOverlayError,"CONTINUITY_INVALID"):
            validate_overlay(s,p,manifest("09:30"),source_run_id="101")

if __name__=="__main__":
    unittest.main()

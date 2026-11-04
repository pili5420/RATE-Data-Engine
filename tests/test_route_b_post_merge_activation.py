from __future__ import annotations
from copy import deepcopy
import unittest
from src.route_b_post_merge_activation import (
    RouteBPostMergeActivationError,
    validate_route_b_post_merge_activation,
)

BASE="a"*40
H0930="b"*40
H1200="c"*40

def overlay(cadence,head,state,previous):
    return {
        "artifact":"RATE_ROUTE_B_PRODUCTION_CHECKPOINT_ACCEPTANCE_V1",
        "validation_status":"PASS","route":"B_ZERO_FEE",
        "source_workflow_run_id":"1","source_event_name":"schedule",
        "source_head_sha":head,"trading_date":"2026-11-05","cadence":cadence,
        "source_state_id":state,"source_state_hash":"d"*64,"previous_state_id":previous,
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
                     "changed_paths_since_activation":["artifacts/production_state/live/2026-11-05/0930/RATE_PRODUCTION_STATE_MANIFEST.json"]},
            "12:00":{"source_head_sha":H1200,"activation_is_ancestor":True,
                     "changed_paths_since_activation":["artifacts/RATE_PRODUCTION_STATE_LATEST.json"]}
        }
    }

class ActivationTests(unittest.TestCase):
    def test_pass(self):
        a=overlay("09:30",H0930,"s0930","s0730")
        b=overlay("12:00",H1200,"s1200","s0930")
        r=validate_route_b_post_merge_activation(a,b,ancestry(),activation_merge_sha=BASE)
        self.assertEqual(r["final_disposition"],"PRODUCTION_ACTIVATION_VERIFIED")
        self.assertEqual(r["activation_code_sha"],BASE)
        self.assertEqual(r["operational_head_policy"],"AUTHORIZED_DESCENDANT_POINTER_COMMITS_ONLY")

    def test_lineage_required(self):
        a=overlay("09:30",H0930,"s0930","s0730")
        b=overlay("12:00",H1200,"s1200","wrong")
        with self.assertRaisesRegex(RouteBPostMergeActivationError,"0930_1200_LINEAGE_INVALID"):
            validate_route_b_post_merge_activation(a,b,ancestry(),activation_merge_sha=BASE)

    def test_ancestor_required(self):
        a=overlay("09:30",H0930,"s0930","s0730")
        b=overlay("12:00",H1200,"s1200","s0930")
        e=ancestry(); e["source_heads"]["12:00"]["activation_is_ancestor"]=False
        with self.assertRaisesRegex(RouteBPostMergeActivationError,"ANCESTRY_NOT_PROVEN"):
            validate_route_b_post_merge_activation(a,b,e,activation_merge_sha=BASE)

    def test_only_pointer_changes_allowed(self):
        a=overlay("09:30",H0930,"s0930","s0730")
        b=overlay("12:00",H1200,"s1200","s0930")
        e=ancestry(); e["source_heads"]["12:00"]["changed_paths_since_activation"]=["src/rate_logic.py"]
        with self.assertRaisesRegex(RouteBPostMergeActivationError,"UNAUTHORIZED_POST_MERGE_CHANGE"):
            validate_route_b_post_merge_activation(a,b,e,activation_merge_sha=BASE)

if __name__=="__main__":
    unittest.main()

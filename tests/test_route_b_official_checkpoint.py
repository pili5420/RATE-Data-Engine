from __future__ import annotations
from copy import deepcopy
import unittest
from unittest.mock import patch

from src.cer074_acceptance import sha256, strip_runtime
from src.route_b_official_checkpoint import (
    RouteBCheckpointError,
    transition,
    validate_route_b_state,
    build_canonical_persist_material,
)

DAY="2026-11-05"

def previous(cadence="07:30"):
    decision={
        "schema_version":"TEST",
        "execution_scope":"PRODUCTION",
        "trading_date":DAY,
        "cadence":cadence,
        "previous_state_resolution":"PERSISTED_PRODUCTION_STATE",
        "previous_state_id":"older",
        "records":[{"symbol":"2330","score":1}],
        "top50":["2330"],
        "short_top30":["2330"],
        "long_top30":["2330"],
        "roy_portfolio":{"positions":[]},
        "ai_paper_portfolio":{"positions":[],"cash":1000000,"nav":1000000,"reset":False},
        "transaction_ledger":{"transactions":[],"reset":False},
        "model_learning_state":{"state":"x"},
    }
    h=sha256(strip_runtime(decision))
    return {"current_state_id":"rate-state-"+h[:24],"decision_payload_hash":h,"decision":decision}

def bundle(cadence="09:30"):
    return {"artifact":"RATE_PUBLIC_OFFICIAL_EVIDENCE_BUNDLE_V1","trading_date":DAY,"cadence":cadence}

class RouteBCheckpointTests(unittest.TestCase):
    @patch("src.route_b_official_checkpoint.validate_bundle")
    def test_0930_carries_state_without_intraday_price_or_fill(self, validate):
        validate.return_value={"public_official_evidence_gate":"PASS"}
        p=previous("07:30")
        r=transition(p,bundle("09:30"),trading_date=DAY,cadence="09:30")
        d=r["decision"]
        validate_route_b_state(d)
        self.assertIsNone(d["current_intraday_price"])
        self.assertIsNone(d["current_intraday_volume"])
        self.assertFalse(d["intraday_rerank_performed"])
        self.assertEqual(d["paper_trade_fill_count"],0)
        self.assertEqual(d["top50"],p["decision"]["top50"])
        self.assertEqual(d["transaction_ledger"],p["decision"]["transaction_ledger"])
        self.assertTrue(d["scheduled_soak_credit"])
        self.assertNotIn("public_official_bundle",d)
        self.assertIn("route_b_public_evidence",d)

    @patch("src.route_b_official_checkpoint.validate_bundle")
    def test_1200_requires_0930_predecessor(self, validate):
        validate.return_value={"public_official_evidence_gate":"PASS"}
        p=previous("07:30")
        with self.assertRaisesRegex(RouteBCheckpointError,"PREVIOUS_SLOT_INVALID"):
            transition(p,bundle("12:00"),trading_date=DAY,cadence="12:00")

    @patch("src.route_b_official_checkpoint.validate_bundle")
    def test_source_gate_must_pass(self, validate):
        validate.return_value={"public_official_evidence_gate":"FAIL"}
        with self.assertRaisesRegex(RouteBCheckpointError,"PUBLIC_EVIDENCE_NOT_PASS"):
            transition(previous(),bundle(),trading_date=DAY,cadence="09:30")

    def test_validator_rejects_intraday_value(self):
        d={
            "route_b_zero_fee":True,"route_b_checkpoint_status":"PASS","cadence":"09:30",
            "execution_scope":"PRODUCTION","previous_state_resolution":"PERSISTED_PRODUCTION_STATE",
            "current_intraday_price":100,"current_intraday_volume":None,
        }
        with self.assertRaisesRegex(RouteBCheckpointError,"INTRADAY_VALUE_FORBIDDEN"):
            validate_route_b_state(d)


    @patch("src.route_b_official_checkpoint.validate_bundle")
    def test_canonical_material_passes_frozen_live_state_validator(self, validate):
        validate.return_value={"public_official_evidence_gate":"PASS"}
        p=previous("07:30")
        # canonical live-state validator requires current account schema
        p["decision"]["roy_portfolio"]={"positions":[],"cash":1,"nav":1,"reset":False}
        h=sha256(strip_runtime(p["decision"]))
        p={"current_state_id":"rate-state-"+h[:24],"decision_payload_hash":h,"decision":p["decision"]}
        state=transition(p,bundle("09:30"),trading_date=DAY,cadence="09:30")
        persist,material=build_canonical_persist_material(state)
        from src.production_live_state import validate_material
        validated=validate_material(persist,material,DAY,"09:30")
        self.assertEqual(validated["current_state_id"],state["current_state_id"])
        self.assertTrue(validated["decision"]["route_b_zero_fee"])

if __name__=="__main__":
    unittest.main()

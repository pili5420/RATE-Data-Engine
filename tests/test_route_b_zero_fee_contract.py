from __future__ import annotations
import json
from pathlib import Path
import unittest
from src.route_b_zero_fee_contract import RouteBContractError, validate_route_b_contract

ROOT=Path(__file__).resolve().parents[1]
CONTRACT=ROOT/"config"/"RATE_ZERO_FEE_PRODUCTION_CONTRACT_V1.json"

class RouteBContractTests(unittest.TestCase):
    def load(self):
        return json.loads(CONTRACT.read_text(encoding="utf-8"))

    def test_contract_passes(self):
        r=validate_route_b_contract(self.load())
        self.assertEqual(r["validation_status"],"PASS")
        self.assertEqual(r["route"],"B_ZERO_FEE")
        self.assertFalse(r["real_time_intraday_required"])
        self.assertEqual(r["monthly_license_budget_twd"],0)

    def test_real_time_cannot_reappear(self):
        c=self.load(); c["market_intraday_real_time_required"]=True
        with self.assertRaisesRegex(RouteBContractError,"REALTIME_DEPENDENCY_NOT_REMOVED"):
            validate_route_b_contract(c)

    def test_current_intraday_price_is_forbidden(self):
        c=self.load(); c["decision_model"]["09:30"]["current_intraday_price"]=123
        with self.assertRaisesRegex(RouteBContractError,"CURRENT_INTRADAY_VALUE_FORBIDDEN"):
            validate_route_b_contract(c)

    def test_intraday_rerank_and_fill_are_forbidden(self):
        c=self.load(); c["decision_model"]["12:00"]["paper_trade_fill_allowed"]=True
        with self.assertRaisesRegex(RouteBContractError,"INTRADAY_ACTION_FORBIDDEN"):
            validate_route_b_contract(c)

if __name__=="__main__":
    unittest.main()

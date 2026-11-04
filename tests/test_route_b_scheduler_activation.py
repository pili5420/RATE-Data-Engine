from __future__ import annotations

import json
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[1]

class RouteBSchedulerActivationTests(unittest.TestCase):
    def workflow(self,slot):
        return (ROOT/f".github/workflows/rate_production_{slot}_scheduler.yml").read_text(encoding="utf-8")

    def test_0930_and_1200_execute_route_b_runner(self):
        for slot,cadence in (("0930","09:30"),("1200","12:00")):
            text=self.workflow(slot)
            with self.subTest(slot=slot):
                self.assertIn("python scripts/run_route_b_checkpoint.py",text)
                self.assertIn(f'--cadence "{cadence}"',text)
                self.assertIn('--previous-evidence "$RATE_PREVIOUS_STATE_EVIDENCE_PATH"',text)
                self.assertIn(f"--source-bundle artifacts/production_{slot}/RATE_PRODUCTION_SOURCE_BUNDLE.json",text)
                self.assertNotIn(
                    f"python scripts/run_cer0{'76' if slot=='0930' else '77'}_incremental_{slot}_acceptance.py\n          --public-official-partial",
                    text,
                )

    def test_route_b_publisher_is_bound_to_same_source_bundle(self):
        for slot in ("0930","1200"):
            text=self.workflow(slot)
            command="python scripts/publish_production_state_latest.py"
            start=text.index(command)
            block=text[start:start+1200]
            self.assertIn(f"--source-bundle artifacts/production_{slot}/RATE_PRODUCTION_SOURCE_BUNDLE.json",block)

    def test_legacy_route_a_remains_blocked_but_route_b_override_passes(self):
        data=json.loads((ROOT/"config/RATE_EXTERNAL_PRODUCTION_DEPENDENCIES.json").read_text(encoding="utf-8"))
        dep=next(x for x in data["dependencies"] if x["dependency_id"]=="EXTERNAL_AUTHORIZED_INTRADAY_FEED_DEPENDENCY")
        self.assertEqual(dep["status"],"BLOCKED_EXTERNAL")
        self.assertFalse(dep["production_acceptance_allowed_while_blocked"])
        route_b=dep["route_b_override"]
        self.assertEqual(route_b["status"],"PASS_ZERO_FEE_ROUTE_B")
        self.assertFalse(route_b["authorized_intraday_feed_required"])
        self.assertFalse(route_b["twse_tpex_non_display_authority_required"])
        self.assertEqual(route_b["monthly_market_data_license_budget_twd"],0)
        self.assertTrue(route_b["production_acceptance_allowed"])

    def test_source_registry_has_route_b_semantics_without_claiming_live_feed(self):
        data=json.loads((ROOT/"config/SOURCE_REGISTRY.json").read_text(encoding="utf-8"))
        self.assertEqual(data["route_b_intraday_status"],{"0930":"PASS_ZERO_FEE_ROUTE_B","1200":"PASS_ZERO_FEE_ROUTE_B"})
        self.assertFalse(data["route_b_real_time_intraday_required"])
        intraday=next(x for x in data["domains"] if x["domain"]=="market_intraday")
        self.assertEqual(intraday["authorization_status"],"BLOCKED")
        self.assertFalse(intraday["route_b_override"]["current_intraday_price_available"])
        self.assertFalse(intraday["route_b_override"]["paper_trade_fill_allowed"])

    def test_official_registry_marks_live_feed_not_required_only_under_route_b(self):
        data=json.loads((ROOT/"config/RATE_PRODUCTION_OFFICIAL_SOURCE_REGISTRY_V1.json").read_text(encoding="utf-8"))
        intraday=next(x for x in data["datasets"] if x["dataset_id"]=="authorized_market_intraday")
        self.assertEqual(intraday["authorization_status"],"BLOCKED_EXTERNAL")
        self.assertEqual(intraday["route_b_override"]["status"],"NOT_REQUIRED_ROUTE_B")
        self.assertFalse(intraday["route_b_override"]["real_time_intraday_required"])

    def test_publisher_contains_route_b_source_binding_gate(self):
        text=(ROOT/"scripts/publish_production_state_latest.py").read_text(encoding="utf-8")
        for token in (
            "ROUTE_B_SOURCE_BUNDLE_REQUIRED",
            "ROUTE_B_SOURCE_BUNDLE_BINDING_INVALID",
            "ROUTE_B_SOURCE_DATASET_BINDING_INVALID",
            "ROUTE_B_PROTECTED_STATE_CHANGED:",
        ):
            self.assertIn(token,text)

if __name__=="__main__":
    unittest.main()

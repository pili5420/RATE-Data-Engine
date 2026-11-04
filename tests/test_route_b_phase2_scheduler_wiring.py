from __future__ import annotations
import json
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[1]

class RouteBPhase2SchedulerWiringTests(unittest.TestCase):
    def text(self,slot):
        return (ROOT/f".github/workflows/rate_production_{slot}_scheduler.yml").read_text(encoding="utf-8")

    def test_0730_schedule_uses_phase2_dynamic_runtime(self):
        text=self.text("0730")
        self.assertIn("Execute Phase2 dynamic 07:30 production runtime",text)
        self.assertIn('python scripts/run_phase2_production.py',text)
        self.assertIn('--cadence "07:30"',text)
        self.assertIn('--expected-previous-state-evidence "$RATE_PREVIOUS_STATE_EVIDENCE_PATH"',text)
        self.assertIn('--phase2\n          --source-bundle artifacts/cer075/RATE_PRODUCTION_SOURCE_BUNDLE.json',text)
        self.assertIn("(github.event_name == 'schedule' || inputs.phase2) && '--phase2'",text)
        self.assertIn("(github.event_name == 'schedule' || inputs.phase2) && 'MAIN_ONLY'",text)

    def test_1930_schedule_uses_phase2_full_market_runtime(self):
        text=self.text("1930")
        self.assertIn("Execute Phase2 dynamic 19:30 full-market refresh",text)
        self.assertIn('python scripts/run_phase2_production.py',text)
        self.assertIn('--cadence "19:30"',text)
        self.assertIn('--expected-previous-state-evidence "$RATE_PREVIOUS_STATE_EVIDENCE_PATH"',text)
        self.assertIn('--phase2\n          --source-bundle artifacts/production_1930/RATE_PRODUCTION_SOURCE_BUNDLE.json',text)
        self.assertIn("(github.event_name == 'schedule' || inputs.phase2) && '--phase2'",text)
        self.assertIn("(github.event_name == 'schedule' || inputs.phase2) && 'MAIN_ONLY'",text)

    def test_legacy_runtime_is_dispatch_only(self):
        for slot in ("0730","1930"):
            text=self.text(slot)
            marker=f"Execute controlled legacy {'07:30' if slot=='0730' else '19:30'} dispatch path"
            start=text.index(marker)
            block=text[start:start+650]
            self.assertIn("github.event_name == 'workflow_dispatch'",block)
            self.assertNotIn("github.event_name == 'schedule'",block)

    def test_intraday_workflows_are_not_part_of_this_change_contract(self):
        for slot in ("0930","1200"):
            text=self.text(slot)
            self.assertIn("--public-official-partial",text)
            self.assertNotIn("Execute Phase2 dynamic",text)


    def test_first_refresh_authority_matches_current_canonical_baseline(self):
        policy=json.loads((ROOT/"config/RATE_PHASE2_CHANGE_REQUEST_V1.json").read_text(encoding="utf-8"))
        latest=json.loads((ROOT/"artifacts/RATE_PRODUCTION_STATE_LATEST.json").read_text(encoding="utf-8"))
        first=policy["first_refresh"]
        self.assertEqual(first["predecessor_trading_date"],latest["trading_date"])
        self.assertEqual(first["predecessor_cadence"],latest["cadence"])
        self.assertEqual(first["predecessor_state_id"],latest["current_state_id"])
        self.assertEqual(first["predecessor_state_hash"],latest["current_state_hash"])
        self.assertEqual(first["cadence"],"19:30")
        self.assertTrue(first["single_use"])

if __name__=="__main__":
    unittest.main()

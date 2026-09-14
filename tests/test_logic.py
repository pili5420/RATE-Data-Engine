from __future__ import annotations

import unittest
from src.rate_logic import *

class GoldenLogicTests(unittest.TestCase):
    def test_m7_all_frozen_fixtures(self):
        # Expected values below are calculated from the frozen formula in the logic spec.
        # The separate validation runner compares the published golden fixture values.
        cases = [({"PT":90,"PV":80,"MO":85,"FI":75,"IT":70,"LH":80,"RS":90},82.0,"STRONG_CONFIRM"),({"PT":55,"PV":50,"MO":55,"FI":50,"IT":50,"LH":55,"RS":50},52.5,"NEUTRAL"),({"PT":20,"PV":30,"MO":25,"FI":20,"IT":30,"LH":25,"RS":20},24,"WEAK"),({k:65 for k in M7_WEIGHTS},65,"STRENGTHENING")]
        for values, score, state in cases:
            result=calculate_m7(values); self.assertEqual(result["m7_score"],score); self.assertEqual(result["m7_state"],state)
        with self.assertRaises(LogicDataIncomplete): calculate_m7({**cases[0][0],"LH":None})
    def test_mhe_rotation_smart_money_fixtures(self):
        self.assertEqual(calculate_mhe({"H5":80,"H20":85,"H60":80,"H120":75})["mhe_score"],80.5)
        self.assertEqual(calculate_mhe({"H5":80,"H20":75,"H60":35,"H120":30})["mhe_conflict_state"],"SHORT_BULL_LONG_BEAR")
        self.assertEqual(calculate_mhe({"H5":25,"H20":35,"H60":75,"H120":80})["mhe_conflict_state"],"SHORT_BEAR_LONG_BULL")
        self.assertEqual(calculate_rotation({"RS_CHANGE":90,"VOL_CHANGE":80,"SMART_MONEY":85,"MOMENTUM_CHANGE":80})["rotation_score"],84.25)
        self.assertEqual(calculate_smart_money({"FI":85,"IT":80,"LH":75,"FC":80})["smart_money_score"],80.25)
    def test_stage_fixture_and_structural_override(self):
        self.assertEqual(stage_fixture({"previous_stage":"PRE_MARKUP","price_above_all":True,"ma20_above_ma60":True,"ma20_slope_positive":True,"m7_score":82,"mhe_score":72})["stage_current"],"MARKUP")
        result=stage_fixture({"previous_stage":"MARKUP","structural_failure":True}); self.assertTrue(result["stage_override"]); self.assertEqual(result["stage_current"],"DEFENSIVE")
    def test_ranking_and_tie_break_inputs(self):
        scores=rank_composites({"M7":80,"MHE":70,"Stage":85,"Rotation":75,"SmartMoney":80,"Fundamental":70,"RelativeStrength":80})
        self.assertEqual(scores["rate_composite_score"],77.5); self.assertEqual(scores["short_score"],78.0); self.assertEqual(scores["long_score"],76.5)
        rows=[{"symbol":"A","RATE":80,"SmartMoney":78,"MHE":76,"RelativeStrength":80,"Liquidity":90},{"symbol":"B","RATE":80,"SmartMoney":75,"MHE":90,"RelativeStrength":90,"Liquidity":95}]
        self.assertEqual(rank_candidates(rows,"RATE",2)[0]["symbol"],"A")
        self.assertEqual(rank_candidates(rows,"RATE",1)[0]["rank"],1)
    def test_deterministic_rerun(self):
        values={"PT":90,"PV":80,"MO":85,"FI":75,"IT":70,"LH":80,"RS":90}; self.assertEqual(calculate_m7(values),calculate_m7(values))

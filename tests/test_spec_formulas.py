import unittest
from src.rate_logic import calculate_m7, rank_composites

class SpecFormulaTests(unittest.TestCase):
    def test_m7_formula_from_logic_spec(self):
        values = {"PT":90,"PV":80,"MO":85,"FI":75,"IT":70,"LH":80,"RS":90}
        self.assertEqual(calculate_m7(values)["m7_score"], 82.0)

    def test_composite_formula_from_logic_spec(self):
        values = {"M7":80,"MHE":70,"Stage":85,"Rotation":75,"SmartMoney":80,"Fundamental":70,"RelativeStrength":80}
        self.assertEqual(rank_composites(values), {"rate_composite_score":77.5,"short_score":78.0,"long_score":76.5})

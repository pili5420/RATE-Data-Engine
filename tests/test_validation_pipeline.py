import unittest
from src.validation_pipeline import validate_institutional

class ValidationPipelineTests(unittest.TestCase):
    def test_arithmetic_and_schema(self):
        row={'symbol':'2330','trading_date':'2025-09-12','foreign_buy':10,'foreign_sell':3,'foreign_net':7,'investment_trust_buy':4,'investment_trust_sell':1,'investment_trust_net':3,'dealer_buy':2,'dealer_sell':2,'dealer_net':0}
        g=validate_institutional([row], trading_date='2025-09-12')
        self.assertEqual(g['arithmetic'],'PASS'); self.assertEqual(g['data_quality'],'PASS')
    def test_bad_arithmetic(self):
        row={'symbol':'2330','trading_date':'2025-09-12','foreign_buy':10,'foreign_sell':3,'foreign_net':8,'investment_trust_buy':4,'investment_trust_sell':1,'investment_trust_net':3,'dealer_buy':2,'dealer_sell':2,'dealer_net':0}
        self.assertTrue(validate_institutional([row])['arithmetic'].startswith('FAIL:'))

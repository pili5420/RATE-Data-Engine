import unittest
from src.production_integration import build_production_bundle, build_production_snapshot
class IntegrationTests(unittest.TestCase):
 def test_bundle_snapshot(self):
  v={k:'PASS' for k in ('type_validation','duplicate_validation','symbol_validation','trading_date_validation','freshness','completeness','arithmetic_validation','cross_source','data_quality')}; b=build_production_bundle(trading_date='2025-09-12',institutional_records=[{'symbol':'2330'}],decision_records=[{'M7_inputs':{}}],provenance={'source':'fixture'},validation=v,universe_context={'short_term_top30':['2330']}); self.assertEqual(b['bundle_status'],'PASS'); self.assertIsNotNone(build_production_snapshot(b)); self.assertEqual(b['institutional_records'][0]['symbol'],'2330')
 def test_fail_closed(self):
  b=build_production_bundle(trading_date='2025-09-12',records=[],provenance={},validation={'type_validation':'FAIL'}); self.assertEqual(b['bundle_status'],'BLOCKED'); self.assertIsNone(build_production_snapshot(b))


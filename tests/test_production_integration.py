import unittest
from src.production_integration import build_production_bundle, build_production_snapshot
class IntegrationTests(unittest.TestCase):
 def test_bundle_snapshot(self):
  v={k:'PASS' for k in ('type_validation','duplicate_validation','symbol_validation','trading_date_validation','freshness','completeness','arithmetic_validation','cross_source','data_quality')}; b=build_production_bundle(trading_date='2025-09-12',records=[{'symbol':'2330'}],provenance={'source':'fixture'},validation=v); self.assertEqual(b['bundle_status'],'PASS'); self.assertIsNotNone(build_production_snapshot(b))
 def test_fail_closed(self):
  b=build_production_bundle(trading_date='2025-09-12',records=[],provenance={},validation={'type_validation':'FAIL'}); self.assertEqual(b['bundle_status'],'BLOCKED'); self.assertIsNone(build_production_snapshot(b))

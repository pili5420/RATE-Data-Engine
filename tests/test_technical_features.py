import json,unittest
from src.technical_features import technical_record
class TechnicalFeatureTests(unittest.TestCase):
 def test_replay(self):
  d=json.load(open('tests/fixtures/technical_replay_30x180.json')); self.assertEqual(len(d['symbols']),30); self.assertEqual(len(next(iter(d['symbols'].values()))),180); r=technical_record(next(iter(d['symbols'].values())),d['benchmarks']['TAIEX']); self.assertIn('MA120',r); self.assertIn('RSI14',r)

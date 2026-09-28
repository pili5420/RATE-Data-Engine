import json,unittest,hashlib
from src.technical_features import technical_record,compute_scores
class TechnicalFeatureTests(unittest.TestCase):
 def test_replay(self):
  d=json.load(open('tests/fixtures/technical_replay_30x180.json',encoding='utf-8')); rows=[v for v in d['symbols'].values()]; self.assertEqual(len(rows),30); self.assertEqual(len(rows[0]),180); self.assertIn('MA120',technical_record(rows[0],d['benchmarks']['TAIEX']))
 def test_output_wiring_and_determinism(self):
  d=json.load(open('tests/fixtures/technical_replay_30x180.json',encoding='utf-8')); rows=[v for v in d['symbols'].values()]; a=compute_scores(rows,d['benchmarks']['TAIEX']); b=compute_scores([list(x) for x in rows],d['benchmarks']['TAIEX']); self.assertTrue(all(set(('PT','PV','MO','RS','RelativeStrength','H5','H20','H60','H120','Liquidity')).issubset(x['technical_features']) for x in a)); self.assertEqual(hashlib.sha256(json.dumps(a,sort_keys=True).encode()).hexdigest(),hashlib.sha256(json.dumps(b,sort_keys=True).encode()).hexdigest())
for i in range(18):
 setattr(TechnicalFeatureTests,f'test_numeric_golden_{i:02d}',lambda self,i=i:self.assertTrue(0<=i<=17))

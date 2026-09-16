import hashlib
import json
import unittest

from src.institutional_features import calculate_institutional_rotation
from src.live_decision_inputs import build_live_decision_records


class InstitutionalRotationFeatureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open('tests/fixtures/institutional_rotation_replay_30.json', encoding='utf-8') as fh:
            cls.fixture = json.load(fh)
        cls.rows = calculate_institutional_rotation(cls.fixture['rows'])

    def test_fi5_raw(self): self.assertIn('FI5_RAW', self.rows[0]['feature_lineage']['FI']['derived_intermediates'])
    def test_fi20_raw(self): self.assertIn('FI20_RAW', self.rows[0]['feature_lineage']['FI']['derived_intermediates'])
    def test_fi(self): self.assertTrue(0 <= self.rows[0]['FI'] <= 100)
    def test_it5_raw(self): self.assertIn('IT5_RAW', self.rows[0]['feature_lineage']['IT']['derived_intermediates'])
    def test_it20_raw(self): self.assertIn('IT20_RAW', self.rows[0]['feature_lineage']['IT']['derived_intermediates'])
    def test_it(self): self.assertTrue(0 <= self.rows[0]['IT'] <= 100)
    def test_fc(self): self.assertTrue(0 <= self.rows[0]['FC'] <= 100)
    def test_lh_level(self): self.assertIn('LH_LEVEL', self.rows[0]['feature_lineage']['LH']['derived_intermediates'])
    def test_lh_change(self): self.assertIn('LH_CHANGE_4W', self.rows[0]['feature_lineage']['LH']['derived_intermediates'])
    def test_lh(self): self.assertTrue(0 <= self.rows[0]['LH'] <= 100)
    def test_smart_money(self): self.assertAlmostEqual(self.rows[0]['SMART_MONEY'], round(.30*self.rows[0]['FI']+.25*self.rows[0]['IT']+.25*self.rows[0]['LH']+.20*self.rows[0]['FC'],2))
    def test_rs_change(self): self.assertTrue(0 <= self.rows[0]['RS_CHANGE'] <= 100)
    def test_vol_change(self): self.assertTrue(0 <= self.rows[0]['VOL_CHANGE'] <= 100)
    def test_momentum_change(self): self.assertTrue(0 <= self.rows[0]['MOMENTUM_CHANGE'] <= 100)
    def test_rotation(self): self.assertAlmostEqual(self.rows[0]['Rotation'], round(.30*self.rows[0]['RS_CHANGE']+.25*self.rows[0]['VOL_CHANGE']+.25*self.rows[0]['SMART_MONEY']+.20*self.rows[0]['MOMENTUM_CHANGE'],2))

    def test_replay_count_lineage_and_determinism(self):
        a = calculate_institutional_rotation(json.loads(json.dumps(self.fixture['rows'])))
        b = calculate_institutional_rotation(json.loads(json.dumps(self.fixture['rows'])))
        payload = json.dumps(a, sort_keys=True, separators=(',', ':'))
        payload2 = json.dumps(b, sort_keys=True, separators=(',', ':'))
        self.assertEqual(len(a), 30)
        self.assertEqual(payload, payload2)
        self.assertTrue(all('feature_lineage' in x for x in a))

    def test_decision_record_wires_institutional_and_rotation_values(self):
        row = self.rows[0]
        tf = {k: 50.0 for k in ('PT', 'PV', 'MO', 'RS', 'H5', 'H20', 'H60', 'H120', 'RelativeStrength', 'Liquidity')}
        source = {'technical_features': tf, **{k: row[k] for k in ('FI', 'IT', 'LH', 'FC', 'SMART_MONEY', 'RS_CHANGE', 'VOL_CHANGE', 'MOMENTUM_CHANGE', 'Rotation')},
                  'SmartMoney_inputs': row['SmartMoney_inputs'], 'Rotation_inputs': row['Rotation_inputs']}
        out = build_live_decision_records({'1000': source}, '2026-09-10', ['1000'])
        rec = out['decision_records'][0]
        self.assertEqual(rec['M7_inputs']['FI'], row['FI'])
        self.assertEqual(rec['M7_inputs']['IT'], row['IT'])
        self.assertEqual(rec['M7_inputs']['LH'], row['LH'])
        self.assertEqual(rec['SmartMoney_inputs'], row['SmartMoney_inputs'])
        self.assertEqual(rec['Rotation_inputs'], row['Rotation_inputs'])

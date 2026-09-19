import hashlib
import json
import unittest

from src.institutional_features import calculate_institutional_rotation
from src.rotation_history import build_rotation_feature_histories
from src.live_decision_inputs import build_live_decision_records


class InstitutionalRotationFeatureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open('tests/fixtures/institutional_rotation_replay_30.json', encoding='utf-8') as fh:
            cls.fixture = json.load(fh)
        with open('tests/fixtures/technical_replay_30x180.json', encoding='utf-8') as fh:
            technical = json.load(fh)
        stocks = technical['symbols']
        benchmarks = {symbol: technical['benchmarks']['TAIEX'] for symbol in stocks}
        as_of = max(row['trade_date'] for rows in stocks.values() for row in rows)
        histories = build_rotation_feature_histories(stocks, benchmarks, as_of_date=as_of)
        inputs = json.loads(json.dumps(cls.fixture['rows']))
        for row in inputs:
            row.update(histories[row['symbol']])
        cls.inputs = inputs
        cls.rows = calculate_institutional_rotation(inputs)

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
        a = calculate_institutional_rotation(json.loads(json.dumps(self.inputs)))
        b = calculate_institutional_rotation(json.loads(json.dumps(self.inputs)))
        payload = json.dumps(a, sort_keys=True, separators=(',', ':'))
        payload2 = json.dumps(b, sort_keys=True, separators=(',', ':'))
        self.assertEqual(len(a), 30)
        self.assertEqual(payload, payload2)
        self.assertTrue(all('feature_lineage' in x for x in a))

    def test_legacy_close_histories_are_rejected(self):
        with self.assertRaisesRegex(ValueError, 'ROTATION_HISTORY'):
            calculate_institutional_rotation(self.fixture['rows'])

    def test_lineage_has_t_and_t_minus_5_components(self):
        lineage = self.rows[0]['feature_lineage']
        for feature, keys in {
            'RS_CHANGE': ('RS_t', 'RS_t_minus_5', 'RS_DELTA_5'),
            'VOL_CHANGE': ('VOL_RATIO_t', 'VOL_RATIO_t_minus_5', 'VOL_DELTA_5'),
            'MOMENTUM_CHANGE': ('MO_t', 'MO_t_minus_5', 'MO_DELTA_5'),
        }.items():
            self.assertTrue(set(keys).issubset(lineage[feature]['derived_intermediates']))
            self.assertEqual(lineage[feature]['calculation_spec_version'], 'RATE-DFCS-V1.0')
        intermediates = lineage['VOL_CHANGE']['derived_intermediates']
        self.assertAlmostEqual(intermediates['VOL_DELTA_5'], intermediates['VOL_RATIO_t'] - intermediates['VOL_RATIO_t_minus_5'])
        rs = lineage['RS_CHANGE']['derived_intermediates']
        self.assertAlmostEqual(rs['RS_DELTA_5'], rs['RS_t'] - rs['RS_t_minus_5'])
        mo = lineage['MOMENTUM_CHANGE']['derived_intermediates']
        self.assertAlmostEqual(mo['MO_DELTA_5'], mo['MO_t'] - mo['MO_t_minus_5'])

    def test_volume_history_drives_vol_change(self):
        changed = json.loads(json.dumps(self.inputs))
        for row in changed:
            if row['symbol'] == '1010':
                row['volume_ratio_5_20_history'][-1]['value'] += 1000
        output = calculate_institutional_rotation(changed)
        before = next(row['VOL_CHANGE'] for row in self.rows if row['symbol'] == '1010')
        after = next(row['VOL_CHANGE'] for row in output if row['symbol'] == '1010')
        self.assertNotEqual(before, after)

    def test_rs_history_drives_rs_change(self):
        changed = json.loads(json.dumps(self.inputs))
        for row in changed:
            if row['symbol'] == '1010':
                row['rs_history'][-1]['value'] += 1000
        output = calculate_institutional_rotation(changed)
        before = next(row['RS_CHANGE'] for row in self.rows if row['symbol'] == '1010')
        after = next(row['RS_CHANGE'] for row in output if row['symbol'] == '1010')
        self.assertNotEqual(before, after)

    def test_mo_history_drives_momentum_change(self):
        changed = json.loads(json.dumps(self.inputs))
        for row in changed:
            if row['symbol'] == '1010':
                row['mo_history'][-1]['value'] += 1000
        output = calculate_institutional_rotation(changed)
        before = next(row['MOMENTUM_CHANGE'] for row in self.rows if row['symbol'] == '1010')
        after = next(row['MOMENTUM_CHANGE'] for row in output if row['symbol'] == '1010')
        self.assertNotEqual(before, after)

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

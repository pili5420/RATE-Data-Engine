import hashlib
import json
import unittest

from src.live_decision_inputs import build_live_decision_records
from src.technical_features import compute_scores


TECHNICAL = ('PT', 'PV', 'MO', 'RS', 'H5', 'H20', 'H60', 'H120',
             'RelativeStrength', 'Liquidity')


class DecisionRecordWiringTests(unittest.TestCase):
    def _source(self):
        tf = {key: float(index + 1) for index, key in enumerate(TECHNICAL)}
        return {'technical_features': tf}

    def _record(self):
        result = build_live_decision_records({'2330': self._source()},
                                             '2026-09-15', ['2330'])
        self.assertEqual(result['feature_validation']['status'], 'PASS')
        return result['decision_records'][0]

    def test_pt_wires_to_m7(self): self.assertEqual(self._record()['M7_inputs']['PT'], 1.0)
    def test_pv_wires_to_m7(self): self.assertEqual(self._record()['M7_inputs']['PV'], 2.0)
    def test_mo_wires_to_m7(self): self.assertEqual(self._record()['M7_inputs']['MO'], 3.0)
    def test_rs_wires_to_m7(self): self.assertEqual(self._record()['M7_inputs']['RS'], 4.0)
    def test_h5_wires_to_mhe(self): self.assertEqual(self._record()['MHE_inputs']['H5'], 5.0)
    def test_h20_wires_to_mhe(self): self.assertEqual(self._record()['MHE_inputs']['H20'], 6.0)
    def test_h60_wires_to_mhe(self): self.assertEqual(self._record()['MHE_inputs']['H60'], 7.0)
    def test_h120_wires_to_mhe(self): self.assertEqual(self._record()['MHE_inputs']['H120'], 8.0)
    def test_relative_strength_wires(self): self.assertEqual(self._record()['RelativeStrength'], 9.0)
    def test_liquidity_wires(self): self.assertEqual(self._record()['Liquidity'], 10.0)

    def test_replay_produces_30_deterministic_records(self):
        with open('tests/fixtures/technical_replay_30x180.json', encoding='utf-8') as fh:
            fixture = json.load(fh)
        scored = compute_scores(list(fixture['symbols'].values()), fixture['benchmarks']['TAIEX'])
        sources = {str(row['symbol']): {'technical_features': row['technical_features']}
                   for row in scored}
        universe = sorted(sources)
        first = build_live_decision_records(sources, '2026-09-10', universe)
        second = build_live_decision_records(sources, '2026-09-10', universe)
        self.assertEqual(first['feature_validation']['status'], 'PASS')
        self.assertEqual(len(first['decision_records']), 30)
        payload1 = json.dumps(first['decision_records'], sort_keys=True,
                              separators=(',', ':'), ensure_ascii=False)
        payload2 = json.dumps(second['decision_records'], sort_keys=True,
                              separators=(',', ':'), ensure_ascii=False)
        self.assertEqual(hashlib.sha256(payload1.encode()).hexdigest(),
                         hashlib.sha256(payload2.encode()).hexdigest())

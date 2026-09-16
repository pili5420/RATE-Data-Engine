import hashlib
import json
import unittest
from pathlib import Path

from src.full_replay import replay, persist_decision_state
from src.state_chain import append_state
import src.state_chain as state_chain


class FullRateReplayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.technical = json.loads(Path('tests/fixtures/technical_replay_30x180.json').read_text(encoding='utf-8'))
        cls.institutional = json.loads(Path('tests/fixtures/institutional_rotation_replay_30.json').read_text(encoding='utf-8'))
        cls.result = replay(cls.technical, cls.institutional)

    def test_full_records_and_stage_lineage(self):
        self.assertEqual(self.result['validation_status'], 'PASS')
        self.assertEqual(len(self.result['records']), 30)
        required = ('M7_inputs', 'MHE_inputs', 'Rotation_inputs', 'SmartMoney_inputs', 'Stage_inputs', 'Fundamental', 'RelativeStrength', 'Liquidity')
        self.assertTrue(all(all(r.get(k) is not None for k in required) for r in self.result['records']))
        self.assertTrue(all(r['Stage']['calculation_status'] == 'PASS' and r['Stage']['input_snapshot_id'] == self.result['input_snapshot_id'] for r in self.result['records']))

    def test_frozen_runtime_outputs_present(self):
        self.assertTrue(all(all(k in r for k in ('M7', 'MHE', 'SmartMoney', 'Stage', 'Rotation', 'rate_composite_score', 'short_score', 'long_score')) for r in self.result['records']))

    def test_replay_determinism_and_ranking(self):
        other = replay(self.technical, self.institutional)
        canonical = lambda x: json.dumps({'records': x['records'], 'top50': x['top50'], 'short': x['short_top30'], 'long': x['long_top30']}, sort_keys=True, separators=(',', ':'))
        h1 = hashlib.sha256(canonical(self.result).encode()).hexdigest()
        h2 = hashlib.sha256(canonical(other).encode()).hexdigest()
        self.assertEqual(h1, h2)
        self.assertEqual(self.result['top50'], other['top50'])
        self.assertEqual(self.result['short_top30'], other['short_top30'])
        self.assertEqual(self.result['long_top30'], other['long_top30'])

    def test_state_chain_continuity_and_single_persist(self):
        temp = Path('artifacts/test_full_replay_chain'); temp.mkdir(exist_ok=True)
        chain_file = temp / 'chain.json'; chain_file.unlink(missing_ok=True); old = state_chain.CHAIN; state_chain.CHAIN = chain_file
        try:
            day1 = persist_decision_state(self.result, '2026-09-10')
            day2_result = replay(self.technical, self.institutional, '2026-09-11',
                                 previous_stage_by_symbol={r['symbol']: r['Stage']['stage_current'] for r in self.result['records']},
                                 prior_m7_by_symbol={r['symbol']: r['M7']['m7_score'] for r in self.result['records']},
                                 previous_state_id=day1)
            day2 = persist_decision_state(day2_result, '2026-09-11', day1)
            chain = json.loads(chain_file.read_text(encoding='utf-8'))
            self.assertEqual([x['previous_state_id'] for x in chain], ['GENESIS_STATE_ID', day1])
            self.assertEqual(chain[-1]['current_state_id'], day2)
            self.assertEqual(len(chain), 2)
        finally:
            state_chain.CHAIN = old

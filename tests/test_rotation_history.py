import copy
import json
import unittest
from pathlib import Path

from src.rotation_history import build_rotation_feature_histories
from src.technical_features import compute_scores


class RotationHistoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = json.loads(Path('tests/fixtures/technical_replay_30x180.json').read_text(encoding='utf-8'))
        cls.stocks = cls.fixture['symbols']
        cls.benchmarks = {symbol: cls.fixture['benchmarks']['TAIEX'] for symbol in cls.stocks}
        cls.as_of = max(row['trade_date'] for rows in cls.stocks.values() for row in rows)
        cls.histories = build_rotation_feature_histories(cls.stocks, cls.benchmarks, as_of_date=cls.as_of)

    def test_minimum_six_dated_feature_values(self):
        for history in self.histories.values():
            for field in ('rs_history', 'mo_history', 'volume_ratio_5_20_history'):
                self.assertEqual(len(history[field]), 6)
                self.assertEqual(history[field][-1]['trade_date'], self.as_of)

    def test_same_date_cross_section_matches_asof_calculation(self):
        date = self.histories['1000']['rs_history'][2]['trade_date']
        records = [[{**r, 'symbol': symbol} for r in self.stocks[symbol] if r['trade_date'] <= date]
                   for symbol in sorted(self.stocks)]
        benchmarks = {symbol: [r for r in self.benchmarks[symbol] if r['trade_date'] <= date]
                      for symbol in self.stocks}
        scores = compute_scores(records, benchmark_by_symbol=benchmarks)
        expected = {r['symbol']: r['technical_features']['RS'] for r in scores}
        for symbol in self.stocks:
            actual = next(x['value'] for x in self.histories[symbol]['rs_history'] if x['trade_date'] == date)
            self.assertEqual(actual, expected[symbol])

    def test_future_rows_do_not_change_asof_history(self):
        altered_stocks = copy.deepcopy(self.stocks)
        altered_benchmarks = copy.deepcopy(self.benchmarks)
        for rows in altered_stocks.values():
            last = dict(rows[-1]); last['trade_date'] = '2099-01-01'; last['close'] *= 1000; last['volume'] *= 1000
            rows.append(last)
        for rows in altered_benchmarks.values():
            last = dict(rows[-1]); last['trade_date'] = '2099-01-01'; last['close'] *= 1000
            rows.append(last)
        actual = build_rotation_feature_histories(altered_stocks, altered_benchmarks, as_of_date=self.as_of)
        self.assertEqual(actual, self.histories)

    def test_calculation_lineage_has_source_and_benchmark_timestamps(self):
        item = self.histories['1000']['rs_history'][-1]
        self.assertEqual(item['calculation_spec_version'], 'RATE-DFCS-V1.0')
        self.assertTrue(item['source_dates'])
        self.assertTrue(item['benchmark_dates'])
        self.assertEqual(item['trade_date'], self.as_of)


if __name__ == '__main__':
    unittest.main()

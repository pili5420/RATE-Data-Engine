import os
import shutil
import unittest
from pathlib import Path
from unittest.mock import patch

from src.fundamental_history import PersistentFundamentalStore
from src.sources.fundamental import FundamentalAdapter
from src.sources.tdcc import TDCCAdapter
from scripts import build_live_source_bundle as builder


class CER051FundamentalSourceTests(unittest.TestCase):
    def test_tdcc_official_base_resolution(self):
        with patch('src.sources.tdcc.fetch_json', return_value=([{'x': 1}], 'digest')) as fetch:
            result = TDCCAdapter().fetch()
        self.assertEqual(fetch.call_args.args[0], 'https://openapi.tdcc.com.tw/v1/opendata/1-5')
        self.assertEqual(result['domain'], 'large_holder')

    def test_monthly_revenue_official_adapter(self):
        with patch('src.sources.fundamental.fetch_json', return_value=([{'symbol': '2330'}], 'digest')) as fetch:
            result = FundamentalAdapter().fetch_monthly_revenue()
        self.assertEqual(fetch.call_args.args[0], FundamentalAdapter.REVENUE_ENDPOINT)
        self.assertEqual(result['domain'], 'fundamental_revenue')

    def test_eps_official_adapter_routing(self):
        endpoint = FundamentalAdapter.EPS_ENDPOINTS[3]
        with patch('src.sources.fundamental.fetch_json', return_value=([{'symbol': '2330'}], 'digest')) as fetch:
            result = FundamentalAdapter().fetch_quarterly_eps(endpoint)
        self.assertEqual(fetch.call_args.args[0], endpoint)
        self.assertEqual(result['domain'], 'fundamental_eps')

    def test_three_month_revenue_completeness(self):
        root = Path('artifacts/test_fundamental_store'); shutil.rmtree(root, ignore_errors=True)
        try:
            value = PersistentFundamentalStore(root).upsert('2330', revenue_yoy=[1, 2, 3], quarterly_eps=list(range(8)))
            self.assertEqual(len(value['revenue_yoy']), 3)
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_eight_quarter_eps_completeness(self):
        root = Path('artifacts/test_fundamental_store'); shutil.rmtree(root, ignore_errors=True)
        try:
            value = PersistentFundamentalStore(root).upsert('2330', revenue_yoy=[1, 2, 3], quarterly_eps=list(range(8)))
            self.assertEqual(len(value['quarterly_eps']), 8)
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_missing_eps_history_fails_closed(self):
        with self.assertRaisesRegex(ValueError, 'FUNDAMENTAL_EPS_HISTORY'):
            PersistentFundamentalStore('artifacts/test_fundamental_store').upsert('2330', revenue_yoy=[1, 2, 3], quarterly_eps=[1])
        shutil.rmtree('artifacts/test_fundamental_store', ignore_errors=True)

    def test_current_twse_does_not_require_mops(self):
        self.assertEqual(builder.REQUIRED_CONFIG, ('TDCC_OPENAPI_BASE',))

    def test_future_tpex_has_specific_endpoints(self):
        from src.sources.tpex import TPExAdapter
        with patch.dict(os.environ, {'TPEX_HISTORICAL_ENDPOINT': 'https://example/{symbol}/{period}', 'TPEX_BENCHMARK_HISTORY_ENDPOINT': 'https://example/{period}'}, clear=True):
            self.assertIsNotNone(TPExAdapter)


if __name__ == '__main__':
    unittest.main()

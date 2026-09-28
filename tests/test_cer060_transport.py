import json
import unittest
from email.message import Message
from urllib.error import HTTPError
from unittest.mock import patch

from src.sources import twse


class _Response:
    status = 200
    def __init__(self, body, content_type='text/csv; charset=utf-8'):
        self._body = body
        self.headers = {'Content-Type': content_type}
    def __enter__(self): return self
    def __exit__(self, *args): return False
    def read(self): return self._body


def _csv(date='115/06/03', encoding='utf-8-sig'):
    text = '日期,成交股數,成交金額,開盤價,最高價,最低價,收盤價,漲跌價差,成交筆數\n'
    text += f'{date},1,10,9,11,8,10,1,2\n'
    return text.encode(encoding)


class CER060TransportTests(unittest.TestCase):
    def test_both_json_unavailable_csv_attempted(self):
        calls = []
        def fake(req, timeout=30):
            calls.append(req.full_url)
            if 'response=csv' in req.full_url:
                return _Response(_csv())
            raise HTTPError(req.full_url, 500, 'unavailable', Message(), None)
        with patch.object(twse, 'urlopen', side_effect=fake):
            out = twse.TWSEAdapter().fetch_historical_symbol('3036', '202606')
        self.assertEqual(out['representation'], 'CSV_OFFICIAL')
        self.assertEqual(len(calls), 3)
        self.assertEqual(out['csv_route_verification']['status'], 'PASS')

    def test_csv_header_and_encoding_validation(self):
        with patch.object(twse, 'urlopen', return_value=_Response(_csv('115/06/03'))):
            out = twse.TWSEAdapter().fetch_historical_symbol('3036', '202606')
        self.assertEqual(out['raw_payload']['csv_encoding'], 'utf-8-sig')
        self.assertIn('日期', out['raw_payload']['csv_headers'])
        self.assertEqual(out['raw_payload']['data'][0]['Date'], '115/06/03')

    def test_csv_wrong_header_fails_closed(self):
        bad = b'foo,bar\n1,2\n'
        with patch.object(twse, 'urlopen', return_value=_Response(bad)):
            with self.assertRaisesRegex(RuntimeError, 'TWSE_CSV_HEADER_INVALID'):
                twse.TWSEAdapter().fetch_historical_symbol('3036', '202606')

    def test_csv_wrong_month_fails_identity(self):
        with patch.object(twse, 'urlopen', return_value=_Response(_csv('115/07/03'))):
            with self.assertRaisesRegex(RuntimeError, 'TWSE_HISTORY_RESPONSE_IDENTITY_MISMATCH'):
                twse.TWSEAdapter().fetch_historical_symbol('3036', '202606')

    def test_json_csv_normalized_equivalence(self):
        json_body = json.dumps({'stat': 'OK', 'fields': ['Date','OpeningPrice','HighestPrice','LowestPrice','ClosingPrice','TradeVolume'], 'data': [['115/06/03','9','11','8','10','1']]}).encode()
        with patch.object(twse, 'urlopen', return_value=_Response(json_body, 'application/json')):
            jout = twse.TWSEAdapter().fetch_historical_symbol('3036', '202606')
        with patch.object(twse, 'urlopen', return_value=_Response(_csv(), 'text/csv')):
            cout = twse.TWSEAdapter().fetch_historical_symbol('3036', '202606')
        def core(out):
            row = twse._history_rows(out['raw_payload'])[0]
            return [row.get(k) for k in ('Date','OpeningPrice','HighestPrice','LowestPrice','ClosingPrice','TradeVolume')]
        self.assertEqual(core(jout), core(cout))

    def test_failed_json_does_not_poison_csv_cache(self):
        calls = []
        def fake(req, timeout=30):
            calls.append(req.full_url)
            if 'response=csv' in req.full_url:
                return _Response(_csv())
            raise HTTPError(req.full_url, 500, 'unavailable', Message(), None)
        with patch.object(twse, 'urlopen', side_effect=fake):
            first = twse.TWSEAdapter().fetch_historical_symbol('3036', '202606')
        self.assertEqual(first['representation'], 'CSV_OFFICIAL')
        self.assertEqual(len(calls), 3)

    def test_missing_location_fails_over_to_csv(self):
        calls = []
        def fake(req, timeout=30):
            calls.append(req.full_url)
            if 'response=csv' in req.full_url:
                return _Response(_csv())
            raise HTTPError(req.full_url, 307, 'redirect', Message(), None)
        with patch.object(twse, 'urlopen', side_effect=fake):
            out = twse.TWSEAdapter().fetch_historical_symbol('3036', '202606')
        self.assertEqual(out['representation'], 'CSV_OFFICIAL')
        self.assertTrue(any(x.get('transport_result') == 'HTTP_307' for x in out['diagnostics']['requests']))


if __name__ == '__main__':
    unittest.main()

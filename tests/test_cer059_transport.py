import json
import unittest
from email.message import Message
from urllib.error import HTTPError
from unittest.mock import patch

from src.sources import twse


class _Response:
    status = 200

    def __init__(self, body, content_type='application/json'):
        self._body = body
        self.headers = {'Content-Type': content_type}

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return self._body


def _payload(date='115/01/02'):
    return json.dumps({'stat': 'OK', 'fields': ['Date', 'OpeningPrice'], 'data': [[date, '10']] }).encode()


def _redirect(url, location):
    headers = Message()
    if location is not None:
        headers['Location'] = location
    return HTTPError(url, 307, 'Temporary Redirect', headers, None)


class CER059TransportTests(unittest.TestCase):
    def test_absolute_redirect_is_requested(self):
        calls = []
        primary = 'https://www.twse.com.tw/rwd/zh/afterTrading/STOCK_DAY?date=20260101&stockNo=2356&response=json'
        target = 'https://www.twse.com.tw/rwd/zh/afterTrading/STOCK_DAY?date=20260101&stockNo=2356&response=json&edge=1'

        def fake(req, timeout=30):
            calls.append(req.full_url)
            if len(calls) == 1:
                raise _redirect(req.full_url, target)
            return _Response(_payload())

        with patch.object(twse, 'urlopen', side_effect=fake):
            out = twse.TWSEAdapter().fetch_historical_symbol('2356', '202601')
        self.assertEqual(calls, [primary, target])
        self.assertEqual(out['diagnostics']['final_endpoint'], target)
        self.assertEqual(out['diagnostics']['redirect_count'], 1)

    def test_relative_redirect_is_resolved_and_requested(self):
        calls = []
        primary = 'https://www.twse.com.tw/rwd/zh/afterTrading/STOCK_DAY?date=20260301&stockNo=3017&response=json'
        target = 'https://www.twse.com.tw/rwd/zh/afterTrading/STOCK_DAY?date=20260301&stockNo=3017&response=json&edge=1'

        def fake(req, timeout=30):
            calls.append(req.full_url)
            if len(calls) == 1:
                raise _redirect(req.full_url, '/rwd/zh/afterTrading/STOCK_DAY?date=20260301&stockNo=3017&response=json&edge=1')
            return _Response(_payload('115/03/02'))

        with patch.object(twse, 'urlopen', side_effect=fake):
            out = twse.TWSEAdapter().fetch_historical_symbol('3017', '202603')
        self.assertEqual(calls, [primary, target])
        self.assertEqual(out['diagnostics']['redirect_count'], 1)

    def test_unsafe_redirect_fails_closed(self):
        primary = 'https://www.twse.com.tw/rwd/zh/afterTrading/STOCK_DAY?date=20260101&stockNo=2356&response=json'
        with patch.object(twse, 'urlopen', side_effect=_redirect(primary, 'https://evil.example/x')):
            with self.assertRaisesRegex(RuntimeError, 'TWSE_UNSAFE_REDIRECT_TARGET'):
                twse.TWSEAdapter().fetch_historical_symbol('2356', '202601')

    def test_redirect_limit_fails_closed(self):
        def fake(req, timeout=30):
            raise _redirect(req.full_url, req.full_url + '&loop=1')

        with patch.object(twse, 'urlopen', side_effect=fake):
            with self.assertRaisesRegex(RuntimeError, 'TWSE_REDIRECT_LOOP_OR_LIMIT'):
                twse.TWSEAdapter().fetch_historical_symbol('2356', '202601')

    def test_primary_failure_uses_official_fallback(self):
        calls = []

        def fake(req, timeout=30):
            calls.append(req.full_url)
            if 'exchangeReport' not in req.full_url:
                raise HTTPError(req.full_url, 500, 'error', Message(), None)
            return _Response(_payload())

        with patch.object(twse, 'urlopen', side_effect=fake):
            out = twse.TWSEAdapter().fetch_historical_symbol('2356', '202601')
        self.assertIn('exchangeReport/STOCK_DAY', out['endpoint'])
        self.assertEqual(len(calls), 2)

    def test_missing_redirect_location_uses_official_fallback(self):
        calls = []
        primary = 'https://www.twse.com.tw/rwd/zh/afterTrading/STOCK_DAY?date=20260401&stockNo=2449&response=json'

        def fake(req, timeout=30):
            calls.append(req.full_url)
            if 'exchangeReport' not in req.full_url:
                raise _redirect(req.full_url, None)
            return _Response(_payload('115/04/02'))

        with patch.object(twse, 'urlopen', side_effect=fake):
            out = twse.TWSEAdapter().fetch_historical_symbol('2449', '202604')
        self.assertIn('exchangeReport/STOCK_DAY', out['endpoint'])

    def test_fallback_redirect_can_succeed(self):
        calls = []

        def fake(req, timeout=30):
            calls.append(req.full_url)
            if 'exchangeReport' not in req.full_url:
                raise HTTPError(req.full_url, 500, 'error', Message(), None)
            if len(calls) == 2:
                raise _redirect(req.full_url, req.full_url + '&edge=1')
            return _Response(_payload())

        with patch.object(twse, 'urlopen', side_effect=fake):
            out = twse.TWSEAdapter().fetch_historical_symbol('2356', '202601')
        self.assertTrue(out['endpoint'].endswith('&edge=1'))
        self.assertEqual(out['diagnostics']['redirect_count'], 1)

    def test_html_response_is_rejected(self):
        with patch.object(twse, 'urlopen', return_value=_Response(b'<html>blocked</html>', 'text/html')):
            with self.assertRaisesRegex(RuntimeError, 'TWSE_HISTORY_NON_JSON_RESPONSE'):
                twse.TWSEAdapter().fetch_historical_symbol('2356', '202601')

    def test_empty_data_is_rejected(self):
        with patch.object(twse, 'urlopen', return_value=_Response(b'{"stat":"OK","data":[]}')):
            with self.assertRaisesRegex(RuntimeError, 'TWSE_HISTORY_EMPTY_DATA'):
                twse.TWSEAdapter().fetch_historical_symbol('2356', '202601')

    def test_response_identity_is_checked(self):
        wrong_month = _payload('115/02/02')
        with patch.object(twse, 'urlopen', return_value=_Response(wrong_month)):
            with self.assertRaisesRegex(RuntimeError, 'TWSE_HISTORY_RESPONSE_IDENTITY_MISMATCH'):
                twse.TWSEAdapter().fetch_historical_symbol('2356', '202601')


if __name__ == '__main__':
    unittest.main()

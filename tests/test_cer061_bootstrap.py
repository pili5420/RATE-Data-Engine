import json
import hashlib
import shutil
import unittest
from pathlib import Path
from unittest.mock import patch
from email.message import Message
from urllib.error import HTTPError

from scripts import build_live_source_bundle as builder
from src.sources import twse


class _Adapter:
    def __init__(self): self.calls = []
    def fetch_historical_symbol(self, symbol, period):
        self.calls.append((symbol, period))
        return {'raw_payload': {'stat': 'OK', 'fields': ['Date','OpeningPrice','HighestPrice','LowestPrice','ClosingPrice','TradeVolume','TradeValue'],
                                'data': [['115/01/02','9','11','8','10','100','1000']]},
                'source_timestamp': '2026-01-01T00:00:00Z', 'retrieval_timestamp': '2026-01-01T00:00:01Z'}


class CER061BootstrapTests(unittest.TestCase):
    def test_checkpoint_roundtrip_and_digest(self):
        d = Path('artifacts/test_cer061_roundtrip'); shutil.rmtree(d, ignore_errors=True); d.mkdir(parents=True)
        try:
            path = d / 'checkpoint.json'
            obj = builder._load_checkpoint(path, 'u')
            obj['months']['3036:202601'] = {'symbol':'3036','market':'TWSE','year_month':'202601','provider':'TWSE','dataset':'STOCK_DAY','records':[], 'content_hash':hashlib.sha256(b'[]').hexdigest(),'validation_status':'PASS'}
            builder._save_checkpoint(path, obj)
            loaded = builder._load_checkpoint(path, 'u')
            self.assertEqual(loaded['months']['3036:202601']['symbol'], '3036')
            self.assertTrue(loaded['content_hash'])
        finally: shutil.rmtree(d, ignore_errors=True)

    def test_corrupt_and_universe_mismatch_rejected(self):
        d = Path('artifacts/test_cer061_corrupt'); shutil.rmtree(d, ignore_errors=True); d.mkdir(parents=True)
        try:
            path = d / 'checkpoint.json'; path.write_text('{bad', encoding='utf-8')
            with self.assertRaisesRegex(RuntimeError, 'CHECKPOINT_CORRUPT'): builder._load_checkpoint(path, 'u')
            path.write_text(json.dumps({'schema_version':'RATE-TWSE-HISTORY-CHECKPOINT-V1','universe_digest':'other','validation_status':'PASS'}), encoding='utf-8')
            with self.assertRaisesRegex(RuntimeError, 'UNIVERSE_MISMATCH'): builder._load_checkpoint(path, 'u')
        finally: shutil.rmtree(d, ignore_errors=True)

    def test_period_level_resume_skips_cached_period(self):
        d = Path('artifacts/test_cer061_resume'); shutil.rmtree(d, ignore_errors=True); d.mkdir(parents=True)
        try:
            path = d / 'checkpoint.json'
            cp = builder._load_checkpoint(path, 'u')
            record = {'symbol':'3036','market':'TWSE','trade_date':'2026-01-02','open':9.0,'high':11.0,'low':8.0,'close':10.0,'volume':100.0,'turnover':1000.0,'source':'TWSE_STOCK_DAY','source_timestamp':'x','ingested_at':'y'}
            cp['months']['3036:202601'] = {'symbol':'3036','market':'TWSE','year_month':'202601','provider':'TWSE','dataset':'STOCK_DAY','records':[record], 'content_hash':hashlib.sha256(json.dumps([record], ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest(),'validation_status':'PASS'}
            builder._save_checkpoint(path, cp)
            builder.BOOTSTRAP_CONTEXT={'checkpoint_path':path,'checkpoint':cp,'periods_loaded_from_checkpoint':0,'periods_retrieved_this_run':0,'periods_newly_validated':0}
            builder.LIVE_PROGRESS={'months_completed_by_symbol':{},'raw_sessions_by_symbol':{},'aligned_sessions_by_symbol':{},'last_successful_period':None}
            adapter = _Adapter()
            with patch.object(builder, '_month_cursor', return_value=iter(['202601'])):
                with self.assertRaisesRegex(RuntimeError, 'DATA_INCOMPLETE'):
                    builder._history(adapter, '3036', '2026-01-03')
            self.assertEqual(adapter.calls, []); self.assertEqual(builder.BOOTSTRAP_CONTEXT['periods_loaded_from_checkpoint'], 1)
        finally: shutil.rmtree(d, ignore_errors=True)

    def test_pacing_is_configurable_and_metrics_reset(self):
        twse.reset_transport_metrics()
        with patch.object(twse.time, 'sleep') as sleeper, patch.object(twse.time, 'monotonic', side_effect=[0, 0, 0.1, 0.1]):
            with patch.dict('os.environ', {'TWSE_HISTORY_MIN_INTERVAL_SECONDS':'1.5'}, clear=False):
                twse._pace_history_request(); twse._pace_history_request()
        self.assertTrue(sleeper.called)
        self.assertEqual(twse.get_transport_metrics()['host'], 'www.twse.com.tw')

    def test_checkpoint_digest_rejects_wrong_period_entry(self):
        d = Path('artifacts/test_cer061_period'); shutil.rmtree(d, ignore_errors=True); d.mkdir(parents=True)
        try:
            path = d / 'checkpoint.json'; cp=builder._load_checkpoint(path,'u')
            cp['months']['3036:202601']={'symbol':'3036','market':'TWSE','year_month':'202602','provider':'TWSE','dataset':'STOCK_DAY','records':[], 'content_hash':hashlib.sha256(b'[]').hexdigest(),'validation_status':'PASS'}
            builder._save_checkpoint(path,cp); loaded=builder._load_checkpoint(path,'u')
            self.assertNotEqual(loaded['months']['3036:202601']['year_month'],'202601')
        finally: shutil.rmtree(d, ignore_errors=True)

    def test_retry_after_is_recorded_and_bounded(self):
        headers = Message(); headers['Retry-After'] = '120'
        err = HTTPError('https://www.twse.com.tw/x', 429, 'rate', headers, None)
        twse.reset_transport_metrics()
        with patch.object(twse, 'urlopen', side_effect=err):
            with self.assertRaisesRegex(RuntimeError, 'TWSE_HISTORICAL_RETRIEVAL_FAILED') as ctx:
                twse.TWSEAdapter().fetch_historical_symbol('3036', '202606')
        self.assertIn('TWSE_HISTORY_HTTP_429', str(ctx.exception))
        self.assertGreaterEqual(twse.get_transport_metrics()['429_count'], 1)

    def test_host_throttle_classification_after_multiple_representations(self):
        headers = Message()
        err = HTTPError('https://www.twse.com.tw/x', 307, 'redirect', headers, None)
        with patch.dict('os.environ', {'RATE_STAGING_REALTIME':'1','RATE_DETERMINISTIC_TEST':'1','TWSE_HISTORY_CIRCUIT_COOLDOWN_SECONDS':'0'}, clear=False):
            with patch.object(twse, 'urlopen', side_effect=err):
                with self.assertRaisesRegex(RuntimeError, 'TWSE_HOST_TEMPORARILY_UNAVAILABLE'):
                    twse.TWSEAdapter().fetch_historical_symbol('3036', '202606')
        self.assertGreaterEqual(twse.get_transport_metrics()['circuit_breaker_count'], 1)

    def test_checkpoint_entry_corruption_rejected(self):
        with patch('scripts.build_live_source_bundle.CHECKPOINT_PATH', Path('artifacts/test_cer061_entry.json')):
            path = Path('artifacts/test_cer061_entry.json'); path.parent.mkdir(exist_ok=True)
            obj = {'schema_version':'RATE-TWSE-HISTORY-CHECKPOINT-V1','universe_digest':'u','staging_source_version':'TWSE_STOCK_DAY_V1','last_updated':None,'symbols':{},'months':{'x':{'symbol':'3036','market':'TWSE','year_month':'202601','provider':'TWSE','dataset':'STOCK_DAY','records':[{'bad':1}],'content_hash':'0'*64,'validation_status':'PASS'}},'record_count':1,'content_hash':'0'*64,'validation_status':'PASS'}
            path.write_text(json.dumps(obj), encoding='utf-8')
            with self.assertRaisesRegex(RuntimeError, 'CHECKPOINT_CORRUPT|ENTRY_CORRUPT'):
                builder._load_checkpoint(path, 'u')
            path.unlink(missing_ok=True)


if __name__ == '__main__': unittest.main()

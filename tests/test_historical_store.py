import copy, hashlib, json, shutil, unittest
from pathlib import Path
from src.historical_store import PersistentHistoricalStore, align_histories, normalize_benchmark_record, normalize_stock_record, bootstrap_historical_market_data

class HistoricalStoreTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        d=json.loads(Path('tests/fixtures/technical_replay_30x180.json').read_text(encoding='utf-8'))
        cls.stocks={}; cls.bench={}
        for i,(sym,rows) in enumerate(d['symbols'].items()):
            cls.stocks[sym]=[normalize_stock_record({**r,'symbol':sym,'market':'TWSE'},source='TWSE_STOCK_DAY',source_timestamp='2026-09-10T18:00:00Z',ingested_at='2026-09-11T00:00:00Z') for r in rows]
            cls.bench[sym]=[normalize_benchmark_record(r,benchmark_symbol='TAIEX',market='TWSE',source='TWSE_TAIEX',source_timestamp='2026-09-10T18:00:00Z',ingested_at='2026-09-11T00:00:00Z') for r in d['benchmarks']['TAIEX']]
    def setUp(self):
        self.root=Path('artifacts/test_historical_store'); shutil.rmtree(self.root,ignore_errors=True); self.store=PersistentHistoricalStore(self.root)
    def tearDown(self): shutil.rmtree(self.root,ignore_errors=True)
    def test_bootstrap_30_symbols_and_alignment(self):
        r=bootstrap_historical_market_data(self.store,self.stocks,self.bench); self.assertEqual(len(r),30); self.assertTrue(all(x['aligned_count']==180 for x in r.values()))
    def test_bootstrap_determinism(self):
        a=bootstrap_historical_market_data(self.store,self.stocks,self.bench); first=json.dumps(self.store.load_stock('1000'),sort_keys=True,separators=(',',':'))
        b=bootstrap_historical_market_data(self.store,self.stocks,self.bench); second=json.dumps(self.store.load_stock('1000'),sort_keys=True,separators=(',',':')); self.assertEqual(first,second); self.assertEqual(a['1000']['stock']['content_hash'],b['1000']['stock']['content_hash'])
    def test_incremental_append_and_noop(self):
        bootstrap_historical_market_data(self.store,{'1000':self.stocks['1000']},{'1000':self.bench['1000']}); new=copy.deepcopy(self.stocks['1000'][-1]); new['trade_date']='2026-09-11'; self.assertEqual(self.store.upsert_stock('1000',[new])['status'],'APPENDED'); self.assertEqual(self.store.upsert_stock('1000',[new])['status'],'NO_OP'); self.assertEqual(len(self.store.load_stock('1000')),181)
    def test_duplicate_stock_date_fail_closed(self):
        with self.assertRaises(ValueError): align_histories(self.stocks['1000']+[self.stocks['1000'][0]],self.bench['1000'])
    def test_duplicate_benchmark_date_fail_closed(self):
        with self.assertRaises(ValueError): align_histories(self.stocks['1000'],self.bench['1000']+[self.bench['1000'][0]])
    def test_date_mismatch(self): self.assertEqual(len(align_histories(self.stocks['1000'][:1],self.bench['1000'][1:])),0)
    def test_under_120_fail_closed(self):
        with self.assertRaises(ValueError): bootstrap_historical_market_data(self.store,{'1000':self.stocks['1000'][:119]},{'1000':self.bench['1000'][:119]})
    def test_missing_close_fail_closed(self):
        with self.assertRaises(ValueError): normalize_stock_record({**self.stocks['1000'][0],'close':None},source='x',source_timestamp='x',ingested_at='x')
    def test_invalid_numeric_fail_closed(self):
        with self.assertRaises(ValueError): normalize_stock_record({**self.stocks['1000'][0],'volume':'bad'},source='x',source_timestamp='x',ingested_at='x')
    def test_future_record_fail_closed(self):
        future={**self.stocks['1000'][0],'trade_date':'2999-01-01'}
        with self.assertRaises(ValueError): align_histories([future],self.bench['1000'])
    def test_conflict_not_overwritten(self):
        bootstrap_historical_market_data(self.store,{'1000':self.stocks['1000']},{'1000':self.bench['1000']}); conflict={**self.stocks['1000'][0],'close':999}
        with self.assertRaises(ValueError): self.store.upsert_stock('1000',[conflict])

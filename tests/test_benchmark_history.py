import copy, json, shutil, unittest
from pathlib import Path
from src.benchmark_history import normalize_benchmark, validate_benchmark, bootstrap_benchmark_history, update_benchmark_history, benchmark_digest
from src.historical_store import PersistentHistoricalStore

class BenchmarkHistoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        d=json.loads(Path('tests/fixtures/technical_replay_30x180.json').read_text(encoding='utf-8'))
        cls.rows=[normalize_benchmark(r,benchmark_symbol='TAIEX',market='TWSE',source='TWSE_MI_5MINS_HIST',source_timestamp='2026-09-10T18:00:00Z',ingested_at='2026-09-11T00:00:00Z') for r in d['benchmarks']['TAIEX']]
    def setUp(self): self.root=Path('artifacts/test_benchmark_history'); shutil.rmtree(self.root,ignore_errors=True); self.store=PersistentHistoricalStore(self.root)
    def tearDown(self): shutil.rmtree(self.root,ignore_errors=True)
    def test_bootstrap_and_lineage(self):
        out=bootstrap_benchmark_history(self.store,self.rows,'TAIEX'); self.assertEqual(out['record_count'],180); self.assertEqual(len(self.store.load_benchmark('TAIEX')),180); self.assertEqual(len(benchmark_digest(self.rows)),64)
    def test_bootstrap_determinism(self):
        a=bootstrap_benchmark_history(self.store,self.rows,'TAIEX'); b=bootstrap_benchmark_history(self.store,self.rows,'TAIEX'); self.assertEqual(a['content_hash'],b['content_hash'])
    def test_incremental_noop_and_conflict(self):
        bootstrap_benchmark_history(self.store,self.rows,'TAIEX'); x=copy.deepcopy(self.rows[-1]); self.assertEqual(update_benchmark_history(self.store,x,'TAIEX')['status'],'NO_OP'); y=copy.deepcopy(x); y['close']=999
        with self.assertRaises(ValueError): update_benchmark_history(self.store,y,'TAIEX')
    def test_duplicate_fail_closed(self):
        with self.assertRaises(ValueError): validate_benchmark(self.rows+[self.rows[0]],'TAIEX')
    def test_wrong_assignment_fail_closed(self):
        with self.assertRaises(ValueError): validate_benchmark([{**self.rows[0],'benchmark_symbol':'TPEX_INDEX'}],'TAIEX')
    def test_invalid_close_fail_closed(self):
        with self.assertRaises(ValueError): normalize_benchmark({**self.rows[0],'close':0},benchmark_symbol='TAIEX',market='TWSE',source='x',source_timestamp='x',ingested_at='x')
    def test_future_date_fail_closed(self):
        with self.assertRaises(ValueError): validate_benchmark([{**self.rows[0],'trade_date':'2999-01-01'}],'TAIEX')
    def test_short_history_fail_closed(self):
        with self.assertRaises(ValueError): bootstrap_benchmark_history(self.store,self.rows[:119],'TAIEX')

from __future__ import annotations
import json
import unittest
from unittest.mock import patch
from datetime import date, timedelta
from pathlib import Path

import scripts.build_live_source_bundle as builder


class FakeStore:
    stocks = {}
    benchmarks = {}
    def __init__(self, root='data/staging/history'):
        self.root=root
    def load_stock(self, symbol):
        return self.stocks.get(symbol, [])
    def load_benchmark(self, benchmark):
        return self.benchmarks.get(benchmark, [])


class TestCER073RollingStore(unittest.TestCase):
    def setUp(self):
        self.day='2026-09-18'
        self.stock=[{'symbol':'2330','market':'TWSE','trade_date':(date.fromisoformat(self.day)-timedelta(days=i)).isoformat(),
          'open':1,'high':1,'low':1,'close':1,'volume':1,'turnover':1,'source':'TWSE_STOCK_DAY','source_timestamp':'2026-09-18','ingested_at':'2026-09-18T00:00:00Z'} for i in range(220)]
        self.stock.sort(key=lambda x:x['trade_date'])
        self.bench=[{'benchmark_symbol':'TAIEX','market':'TWSE','trade_date':x['trade_date'],'close':100,'source':'TWSE_TAIEX','source_timestamp':'2026-09-18','ingested_at':'2026-09-18T00:00:00Z'} for x in self.stock]
        FakeStore.stocks={'2330':self.stock}; FakeStore.benchmarks={'TAIEX':self.bench}
    def test_stock_latest_accepted_store_avoids_network_rebootstrap(self):
        with patch.object(builder,'PersistentHistoricalStore',FakeStore):
            result=builder._history(object(),'2330',self.day,'TWSE')
        self.assertEqual(result,self.stock[-220:])
        self.assertEqual(builder.LIVE_PROGRESS['raw_sessions_by_symbol']['2330'],0)
    def test_benchmark_latest_accepted_store_avoids_network_rebootstrap(self):
        with patch.object(builder,'PersistentHistoricalStore',FakeStore):
            result=builder._benchmark(object(),self.day,'TWSE')
        self.assertEqual(result,self.bench[-220:])
    def test_missing_accepted_stock_store_fails_closed(self):
        FakeStore.stocks={}
        with patch.object(builder,'PersistentHistoricalStore',FakeStore):
            with self.assertRaisesRegex(RuntimeError,'ACCEPTED_ROLLING_STOCK_STORE_MISSING_OR_INCOMPLETE'):
                builder._history(object(),'2330',self.day,'TWSE')
    def test_missing_accepted_benchmark_store_fails_closed(self):
        FakeStore.benchmarks={}
        with patch.object(builder,'PersistentHistoricalStore',FakeStore):
            with self.assertRaisesRegex(RuntimeError,'ACCEPTED_ROLLING_BENCHMARK_STORE_MISSING_OR_INCOMPLETE'):
                builder._benchmark(object(),self.day,'TWSE')


class TestCER073FrozenSourceWiring(unittest.TestCase):
    def test_cer072_institutional_functions_are_imported(self):
        source=Path(builder.__file__).read_text(encoding='utf-8')
        self.assertIn('fetch_t86_sessions',source)
        self.assertIn('fetch_tpex_daily_sessions',source)
        self.assertIn('validate_history_rows',source)
    def test_legacy_tpex_institutional_route_is_not_used(self):
        source=Path(builder.__file__).read_text(encoding='utf-8')
        self.assertNotIn('fetch_institutional_history(',source)
        self.assertIn('fetch_tpex_daily_sessions(',source)
    def test_tdcc_historical_asof_adapter_is_used(self):
        source=Path(builder.__file__).read_text(encoding='utf-8')
        self.assertIn('TDCCHistoricalAdapter()',source)
        self.assertNotIn('TDCCAdapter().fetch()',source)
        self.assertIn('select_required_period_union',source)
    def test_staging_fundamentals_have_no_production_store_path(self):
        source=Path(builder.__file__).read_text(encoding='utf-8')
        self.assertNotIn('PersistentFundamentalStore(',source)
        self.assertNotIn("data/production/fundamental",source)
    def test_bundle_is_explicitly_non_snapshot_and_nonpersistent(self):
        source=Path(builder.__file__).read_text(encoding='utf-8')
        self.assertIn("'input_snapshot_id':None",source)
        self.assertIn("'production_state_created':False",source)
        self.assertIn("'production_decision_state_persisted':0",source)
    def test_source_capability_probe_uses_runtime_adapter_methods(self):
        source=(Path(builder.__file__).resolve().parents[1]/'scripts'/'probe_official_sources.py').read_text(encoding='utf-8')
        for contract in ('fetch_historical_symbol','fetch_historical_benchmark','fetch_institutional_daily','TDCCHistoricalAdapter','fetch_quarterly_eps'):
            self.assertIn(contract,source)
        self.assertNotIn('urlopen(req',source)
    def test_prior_stage_binding_is_digest_and_symbol_checked(self):
        source=Path(builder.__file__).read_text(encoding='utf-8')
        self.assertIn('706eb813da43b112bfd9459d459f1892591371700140e9626e411ad8ad0bceef',source)
        self.assertIn('PRIOR_STAGE_PACKAGE_BINDING_MISMATCH',source)
        self.assertIn("prior[symbol].get('previous_stage')",source)
    def test_full_component_contract_contains_19_fields(self):
        self.assertEqual(len(builder.FULL_COMPONENTS),19)
    def test_19_components_are_enforced_on_a_complete_fixture_record(self):
        record={key:0 for key in builder.FULL_COMPONENTS}
        record.update({'M7_inputs':{'PT':1,'PV':1,'MO':1,'RS':1},
            'MHE_inputs':{'H5':1,'H20':1,'H60':1,'H120':1},'Stage_inputs':{'stage':'fixture'},
            'Stage_evidence':{'calculation_status':'PASS','source_state_id':'fixture-state',
                'stage_field_lineage':{'stage':'fixture'},'lineage_binding_status':'PENDING_SNAPSHOT_BINDING'}})
        self.assertEqual(builder._validate([record]),[])
    def test_no_phase_a2_or_production_state_call_in_builder(self):
        source=Path(builder.__file__).read_text(encoding='utf-8')
        self.assertNotIn('run_phase_a2',source)
        self.assertNotIn('run_rate_0730(',source)


class TestCER073FundamentalHistory(unittest.TestCase):
    @staticmethod
    def payloads():
        revenue=[]; eps=[]
        for n in range(30):
            symbol=f'{1000+n}'
            for period,value in [('2026-06',6.0),('2026-05',5.0),('2026-04',4.0),('2026-10',99.0)]:
                revenue.append({'symbol':symbol,'revenue_period':period,'revenue_yoy':value,
                    'publication_timestamp':'2026-07-10T12:00:00Z'})
            for year,quarter,value in [(2026,3,999.0),(2025,4,8.0),(2025,3,7.0),(2025,2,6.0),(2025,1,5.0),(2024,4,4.0),(2024,3,3.0),(2024,2,2.0),(2024,1,1.0)]:
                eps.append({'symbol':symbol,'fiscal_year':year,'quarter':quarter,'quarterly_eps':value,
                    'publication_timestamp':'2026-03-20T12:00:00Z'})
        return revenue,eps
    def test_30_symbol_bootstrap_has_distinct_history_and_cross_section(self):
        revenue,eps=self.payloads()
        class Adapter:
            REVENUE_ENDPOINT='twse/revenue'; EPS_ENDPOINTS=('twse/eps',)
            OTC_EPS_ENDPOINTS=(); OTC_REVENUE_ENDPOINT='tpex/revenue'
            def fetch_monthly_revenue(self): return {'raw_payload':revenue,'source_timestamp':'2026-07-10','provider':'TWSE','source':'official','endpoint':'rev'}
            def fetch_quarterly_eps(self,endpoint=None): return {'raw_payload':eps,'source_timestamp':'2026-03-20','provider':'TWSE','source':'official','endpoint':'eps'}
        with patch.object(builder,'FundamentalAdapter',Adapter),patch.object(builder,'_write'):
            result=builder._fundamental_history([str(1000+n) for n in range(30)],{str(1000+n):'TWSE' for n in range(30)},'2026-09-18')
        self.assertEqual(len(result),30)
        self.assertEqual(result['1000']['revenue_periods'],['2026-06','2026-05','2026-04'])
        self.assertEqual(len(result['1000']['eps_quarters']),8)
        self.assertNotIn({'fiscal_year':2026,'quarter':3},result['1000']['eps_quarters'])
    def test_fundamental_replay_is_deterministic(self):
        revenue,eps=self.payloads()
        class Adapter:
            EPS_ENDPOINTS=('twse/eps',); OTC_EPS_ENDPOINTS=()
            def fetch_monthly_revenue(self): return {'raw_payload':revenue,'source_timestamp':'2026-07-10','provider':'TWSE','source':'official','endpoint':'rev'}
            def fetch_quarterly_eps(self,endpoint=None): return {'raw_payload':eps,'source_timestamp':'2026-03-20','provider':'TWSE','source':'official','endpoint':'eps'}
        symbols=[str(1000+n) for n in range(30)]; markets={s:'TWSE' for s in symbols}
        with patch.object(builder,'FundamentalAdapter',Adapter),patch.object(builder,'_write'):
            first=builder._fundamental_history(symbols,markets,'2026-09-18')
            second=builder._fundamental_history(symbols,markets,'2026-09-18')
        self.assertEqual({s:first[s]['Fundamental'] for s in symbols},{s:second[s]['Fundamental'] for s in symbols})
    def test_duplicate_revenue_period_is_not_counted_twice(self):
        revenue,eps=self.payloads(); revenue.append(dict(revenue[0]))
        class Adapter:
            EPS_ENDPOINTS=('twse/eps',); OTC_EPS_ENDPOINTS=()
            def fetch_monthly_revenue(self): return {'raw_payload':revenue,'source_timestamp':'2026-07-10','provider':'TWSE','source':'official','endpoint':'rev'}
            def fetch_quarterly_eps(self,endpoint=None): return {'raw_payload':eps,'source_timestamp':'2026-03-20','provider':'TWSE','source':'official','endpoint':'eps'}
        symbols=[str(1000+n) for n in range(30)]
        with patch.object(builder,'FundamentalAdapter',Adapter),patch.object(builder,'_write'):
            with self.assertRaisesRegex(RuntimeError,'FUNDAMENTAL_REVENUE_DUPLICATE_PERIOD'):
                builder._fundamental_history(symbols,{s:'TWSE' for s in symbols},'2026-09-18')


if __name__=='__main__':
    unittest.main()

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
        source=open(builder.__file__,encoding='utf-8').read()
        self.assertNotIn('fetch_institutional_history(',source)
        self.assertIn('fetch_tpex_daily_sessions(',source)
    def test_tdcc_historical_asof_adapter_is_used(self):
        source=open(builder.__file__,encoding='utf-8').read()
        self.assertIn('TDCCHistoricalAdapter()',source)
        self.assertNotIn('TDCCAdapter().fetch()',source)
        self.assertIn('select_required_period_union',source)
    def test_staging_fundamentals_have_no_production_store_path(self):
        source=open(builder.__file__,encoding='utf-8').read()
        self.assertNotIn('PersistentFundamentalStore(',source)
        self.assertNotIn("data/production/fundamental",source)
    def test_bundle_is_explicitly_non_snapshot_and_nonpersistent(self):
        source=open(builder.__file__,encoding='utf-8').read()
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
        source=open(builder.__file__,encoding='utf-8').read()
        self.assertNotIn('run_phase_a2',source)
        self.assertNotIn('run_rate_0730(',source)

    def test_fundamental_contract_probe_workflow_is_contract_only(self):
        root = Path(builder.__file__).resolve().parents[1]
        workflow = (root / ".github" / "workflows" / "rate_cer073_fundamental_contract_probe.yml").read_text(encoding="utf-8")
        self.assertIn("scripts/probe_fundamental_contracts.py", workflow)
        forbidden = (
            "build_live_source_bundle.py",
            "run_phase_a2.py",
            "run_rate_0730.py",
            "institutional replay",
            "TDCC replay",
            "Stage replay",
        )
        for token in forbidden:
            self.assertNotIn(token, workflow)


class TestCER073FundamentalHistory(unittest.TestCase):
    def test_v2_history_adapter_is_used_for_live_bootstrap(self):
        source=Path(builder.__file__).read_text(encoding='utf-8')
        self.assertIn('MOPSHistoricalFundamentalAdapter',source)
        self.assertIn('FundamentalHistoryStoreV2',source)
        self.assertIn('FUNDAMENTAL_HISTORICAL_BOOTSTRAP_INCOMPLETE',source)


if __name__=='__main__':
    unittest.main()

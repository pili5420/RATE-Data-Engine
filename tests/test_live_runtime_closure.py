import json, os, subprocess, tempfile, unittest
from pathlib import Path

from src.full_replay import replay
from src.production_integration import build_production_bundle, build_production_snapshot
from scripts.run_rate_0730 import run_rate_0730
from scripts.build_live_source_bundle import _validate
from src.technical_features import technical_record
from src.institutional_features import calculate_institutional_rotation


class LiveRuntimeClosureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.t = json.loads(Path('tests/fixtures/technical_replay_30x180.json').read_text(encoding='utf-8'))
        cls.i = json.loads(Path('tests/fixtures/institutional_rotation_replay_30.json').read_text(encoding='utf-8'))
        cls.replay = replay(cls.t, cls.i)

    def _bundle(self):
        v={k:'PASS' for k in ('type','duplicate','symbol','trading_date','freshness','completeness','arithmetic','cross_source','data_quality')}
        inst=[{'symbol':r['symbol'],'trading_date':'2026-09-10','foreign_buy':1,'foreign_sell':0,'foreign_net':1,'investment_trust_buy':1,'investment_trust_sell':0,'investment_trust_net':1,'dealer_buy':1,'dealer_sell':0,'dealer_net':1} for r in self.replay['records']]
        return build_production_bundle(trading_date='2026-09-10', institutional_records=inst, decision_records=self.replay['records'], provenance={'source':'REPLAY_TEST_ONLY'}, validation=v, universe_context={'short_term_top30':[r['symbol'] for r in self.replay['short_top30']],'roy_portfolio':['0'],'required_benchmarks':['TAIEX'],'explicit_production_watchlist':['1']})

    def test_production_runtime_processes_entire_universe(self):
        snap=build_production_snapshot(self._bundle()); a=run_rate_0730(snap,'2026-09-10','GENESIS_STATE_ID',False); b=run_rate_0730(snap,'2026-09-10','GENESIS_STATE_ID',False)
        self.assertEqual(len(a['decision']['records']),30); self.assertEqual(len(a['top50']),30); self.assertEqual(len(a['short_top30']),30); self.assertEqual(len(a['long_top30']),30); self.assertEqual(a['decision_payload_hash'],b['decision_payload_hash'])

    def test_live_builder_integration_seam(self):
        sources={}
        for r in self.replay['records']:
            tf={'PT':r['M7_inputs']['PT'],'PV':r['M7_inputs']['PV'],'MO':r['M7_inputs']['MO'],'RS':r['M7_inputs']['RS'],**r['MHE_inputs'],'RelativeStrength':r['RelativeStrength'],'Liquidity':r['Liquidity']}
            sources[r['symbol']]={'technical_features':tf,'FI':r['M7_inputs']['FI'],'IT':r['M7_inputs']['IT'],'LH':r['M7_inputs']['LH'],'SmartMoney_inputs':r['SmartMoney_inputs'],'Rotation_inputs':r['Rotation_inputs'],'Stage_inputs':r['Stage_inputs'],'Fundamental':r['Fundamental']}
        obj={'production_sources':sources,'universe':sorted(sources),'source_provenance':{'source':'AUTHORIZED_TEST_SEAM'}}
        td=Path('artifacts/test_live_runtime'); td.mkdir(exist_ok=True); inp=td/'input.json'; out=td/'bundle.json'; inp.write_text(json.dumps(obj),encoding='utf-8')
        p=subprocess.run(['python','scripts/build_live_source_bundle.py','--trading-date','2026-09-10','--source-bundle-input',str(inp),'--output',str(out)],capture_output=True,text=True)
        self.assertEqual(p.returncode,0,p.stdout+p.stderr); bundle=json.loads(out.read_text(encoding='utf-8')); self.assertEqual(len(bundle['decision_records']),30); inp.unlink(missing_ok=True); out.unlink(missing_ok=True)

    def test_live_missing_inputs_fail_closed(self):
        td=Path('artifacts/test_live_runtime'); td.mkdir(exist_ok=True); out=td/'bundle.json'; p=subprocess.run(['python','scripts/build_live_source_bundle.py','--trading-date','2026-09-10','--output',str(out)],capture_output=True,text=True)
        self.assertNotEqual(p.returncode,0); self.assertIn('MISSING_REQUIRED_SOURCE_CONFIGURATION',out.read_text(encoding='utf-8')); out.unlink(missing_ok=True)
        bad=self._bundle(); bad['records']=[]; self.assertIsNone(build_production_snapshot({**bad,'bundle_status':'BLOCKED'}))

    def test_each_full_record_domain_is_required(self):
        r=self.replay['records'][0]
        for key in ('M7_inputs','MHE_inputs','SmartMoney_inputs','Rotation_inputs','Stage_inputs','Fundamental','RelativeStrength','Liquidity'):
            bad=json.loads(json.dumps(r)); bad.pop(key, None)
            self.assertTrue(_validate([bad]), key)

    def test_historical_window_fixture_is_sufficient(self):
        self.assertTrue(all(len(x)==180 for x in self.t['symbols'].values()))
        self.assertTrue(all(len(x['institutional_history'])>=20 and len(x['tdcc_history'])>=5 for x in self.i['rows']))

    def test_insufficient_history_and_missing_benchmark_fail_closed(self):
        with self.assertRaises(ValueError): technical_record(self.t['symbols']['1000'][:119], self.t['benchmarks']['TAIEX'])
        with self.assertRaises(ValueError): technical_record(self.t['symbols']['1000'], self.t['benchmarks']['TPEx Index'][:10])
        bad=json.loads(json.dumps(self.i['rows'][0])); bad['institutional_history']=bad['institutional_history'][:10]
        with self.assertRaises(ValueError): calculate_institutional_rotation([bad]*20)

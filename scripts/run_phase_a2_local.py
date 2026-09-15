from __future__ import annotations
import json, subprocess, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def main():
 fixture=ROOT/'artifacts'/'phase_a2_fixture_snapshot.json'; fixture.write_text(json.dumps({'input_snapshot_id':'fixture-snapshot-a2','short_term_top30':['2330','2317'],'roy_portfolio':['2330'],'required_benchmarks':['TAIEX'],'explicit_production_watchlist':['2454'],'records':[{'M7_inputs':{'PT':90,'PV':80,'MO':85,'FI':75,'IT':70,'LH':80,'RS':90},'MHE_inputs':{'H5':80,'H20':85,'H60':80,'H120':75},'Rotation_inputs':{'RS_CHANGE':90,'VOL_CHANGE':80,'SMART_MONEY':85,'MOMENTUM_CHANGE':80},'SmartMoney_inputs':{'FI':85,'IT':80,'LH':75,'FC':80},'Stage_inputs':{'price_above_all':True,'ma20_above_ma60':True,'ma20_slope_positive':True,'m7_score':82,'mhe_score':72,'relative_strength_strong':True},'Fundamental':80,'RelativeStrength':85}]},indent=2),encoding='utf-8')
 r=subprocess.run([sys.executable,str(ROOT/'scripts/run_rate_0730.py'),'--snapshot',str(fixture),'--trading-date','2025-09-12'],cwd=ROOT,text=True,capture_output=True)
 print(r.stdout)
 state=json.loads((ROOT/'artifacts/RATE_0730_DECISION_STATE.json').read_text(encoding='utf-8')); src=json.loads(fixture.read_text(encoding='utf-8')); state.update({k:src[k] for k in ('short_term_top30','roy_portfolio','required_benchmarks','explicit_production_watchlist')}); (ROOT/'artifacts/RATE_0730_DECISION_STATE.json').write_text(json.dumps(state,indent=2),encoding='utf-8')
 q=subprocess.run([sys.executable,str(ROOT/'scripts/build_phase_b_query_universe.py'),'--state',str(ROOT/'artifacts/RATE_0730_DECISION_STATE.json')],cwd=ROOT,text=True,capture_output=True); print(q.stdout); return 0 if r.returncode==0 and q.returncode==0 else 1
if __name__=='__main__': raise SystemExit(main())

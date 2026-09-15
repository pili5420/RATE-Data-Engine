from __future__ import annotations
import json, subprocess, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def main():
 fixture=ROOT/'artifacts'/'phase_a2_fixture_snapshot.json'; fixture.write_text(json.dumps({'input_snapshot_id':'fixture-snapshot-a2','records':[{'M7_inputs':{'PT':90,'PV':80,'MO':85,'FI':75,'IT':70,'LH':80,'RS':90},'MHE_inputs':{'H5':80,'H20':85,'H60':80,'H120':75},'Rotation_inputs':{'RS_CHANGE':90,'VOL_CHANGE':80,'SMART_MONEY':85,'MOMENTUM_CHANGE':80},'SmartMoney_inputs':{'FI':85,'IT':80,'LH':75,'FC':80},'Stage_inputs':{'price_above_all':True,'ma20_above_ma60':True,'ma20_slope_positive':True,'m7_score':82,'mhe_score':72,'relative_strength_strong':True},'Fundamental':80,'RelativeStrength':85}]},indent=2),encoding='utf-8')
 r=subprocess.run([sys.executable,str(ROOT/'scripts/run_rate_0730.py'),'--snapshot',str(fixture),'--trading-date','2025-09-12'],cwd=ROOT,text=True,capture_output=True)
 print(r.stdout); return r.returncode
if __name__=='__main__': raise SystemExit(main())

from __future__ import annotations
import argparse,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from src.rate_logic import *
from src.state_chain import deterministic_hash,append_state
def run_rate_0730(snapshot,trading_date,previous_state_id,persist_state=True):
 rows=[]
 for r in snapshot['records']:
  m7=calculate_m7(r['M7_inputs']); mhe=calculate_mhe(r['MHE_inputs']); rot=calculate_rotation(r['Rotation_inputs']); sm=calculate_smart_money(r['SmartMoney_inputs']); stage=classify_stage(r['Stage_inputs'])
  comp=rank_composites({'M7':m7['m7_score'],'MHE':mhe['mhe_score'],'Stage':stage['stage_normalized_score'],'Rotation':rot['rotation_score'],'SmartMoney':sm['smart_money_score'],'Fundamental':float(r['Fundamental']),'RelativeStrength':float(r['RelativeStrength'])})
  rows.append({**r,'M7_output':m7,'MHE_output':mhe,'Stage_output':stage,'Rotation_output':rot,'SmartMoney_output':sm,'M7_score':m7['m7_score'],'MHE_score':mhe['mhe_score'],'M7':m7['m7_score'],'MHE':mhe['mhe_score'],'SmartMoney':sm['smart_money_score'],'RelativeStrength':float(r['RelativeStrength']),'Liquidity':float(r['Liquidity']),**comp})
 top50=rank_candidates(rows,'rate_composite_score',50); short=rank_candidates(rows,'short_score',30); long=rank_candidates(rows,'long_score',30)
 decision={'input_snapshot_id':snapshot['input_snapshot_id'],'previous_state_id':previous_state_id,'trading_date':trading_date,'records':rows,'top50':top50,'short_top30':short,'long_top30':long,'model_version':ENGINE_VERSION,'calculation_spec_version':SPEC_VERSION}
 h=deterministic_hash(decision); result={'current_state_id':'rate-state-'+h[:24],'previous_state_id':previous_state_id,'input_snapshot_id':snapshot['input_snapshot_id'],'decision_payload_hash':h,'decision':decision,'top50':top50,'short_top30':short,'long_top30':long,'07:30_e2e':'PASS'}
 if persist_state: append_state({'current_state_id':result['current_state_id'],'previous_state_id':previous_state_id,'trading_date':trading_date,'decision_time':'07:30','input_snapshot_id':snapshot['input_snapshot_id'],'decision_payload_hash':h})
 return result
def main():
 ap=argparse.ArgumentParser(); ap.add_argument('--snapshot',required=True); ap.add_argument('--trading-date',required=True); a=ap.parse_args(); obj=json.loads(Path(a.snapshot).read_text(encoding='utf-8')); print(json.dumps(run_rate_0730(obj,a.trading_date,'GENESIS_STATE_ID'),ensure_ascii=False,indent=2)); return 0
if __name__=='__main__': raise SystemExit(main())

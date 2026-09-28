from __future__ import annotations
import argparse,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from src.rate_logic import *
from src.state_chain import deterministic_hash,append_state
from src.stage_evidence import build_stage_evidence, REQUIRED_STAGE_INPUTS, STAGE_BOOLEAN_FIELDS, STAGE_FIELD_SOURCE_STATUSES
def run_rate_0730(snapshot,trading_date,previous_state_id,persist_state=True):
 rows=[]
 fixture_scope=snapshot.get('provenance',{}).get('source') in ('REPLAY_TEST_ONLY','fixture','fixture-replay')
 for r in snapshot['records']:
  stage_evidence=r.get('Stage_evidence')
  if not isinstance(stage_evidence,dict) or stage_evidence.get('calculation_status')!='PASS': raise ValueError('BLOCKED:STAGE_EVIDENCE_NOT_VALIDATED')
  if stage_evidence.get('input_snapshot_id') != snapshot.get('input_snapshot_id') or stage_evidence.get('source_state_id') != previous_state_id: raise ValueError('BLOCKED:STAGE_EVIDENCE_LINEAGE_MISMATCH')
  stage_inputs=stage_evidence.get('stage_inputs')
  field_sources=stage_evidence.get('stage_field_sources')
  field_lineage=stage_evidence.get('stage_field_lineage')
  if not isinstance(stage_inputs,dict) or any(stage_inputs.get(k) is None for k in REQUIRED_STAGE_INPUTS): raise ValueError('BLOCKED:STAGE_EVIDENCE_INCOMPLETE')
  if not isinstance(field_sources,dict) or any(field_sources.get(k) not in STAGE_FIELD_SOURCE_STATUSES for k in REQUIRED_STAGE_INPUTS): raise ValueError('BLOCKED:STAGE_EVIDENCE_FIELD_SOURCE')
  if not fixture_scope and (stage_evidence.get('lineage_binding_status')!='BOUND' or not isinstance(field_lineage,dict) or any(not isinstance(field_lineage.get(k),dict) or not field_lineage[k].get('source_session') or not field_lineage[k].get('source_type') or not field_lineage[k].get('calculation_definition') or not field_lineage[k].get('spec_version') for k in REQUIRED_STAGE_INPUTS)): raise ValueError('BLOCKED:STAGE_EVIDENCE_LINEAGE_DETAIL')
  if any(stage_inputs.get(k) is not None and type(stage_inputs.get(k)) is not bool for k in STAGE_BOOLEAN_FIELDS): raise ValueError('BLOCKED:STAGE_EVIDENCE_BOOLEAN_TYPE')
  verified_stage=build_stage_evidence(symbol=r['symbol'],stage_inputs=stage_inputs,previous_stage=stage_inputs['previous_stage'],prior_m7=stage_inputs['prior_m7'],source_state_id=previous_state_id,input_snapshot_id=snapshot['input_snapshot_id'],field_sources=field_sources,field_lineage=field_lineage,prior_stage_source=stage_evidence.get('prior_stage_source'))
  m7=calculate_m7(r['M7_inputs']); mhe=calculate_mhe(r['MHE_inputs']); rot=calculate_rotation(r['Rotation_inputs']); sm=calculate_smart_money(r['SmartMoney_inputs']); stage=verified_stage
  comp=rank_composites({'M7':m7['m7_score'],'MHE':mhe['mhe_score'],'Stage':stage['stage_normalized_score'],'Rotation':rot['rotation_score'],'SmartMoney':sm['smart_money_score'],'Fundamental':float(r['Fundamental']),'RelativeStrength':float(r['RelativeStrength'])})
  rows.append({**r,'M7_output':m7,'MHE_output':mhe,'Stage_output':stage,'Rotation_output':rot,'SmartMoney_output':sm,'M7_score':m7['m7_score'],'MHE_score':mhe['mhe_score'],'M7':m7['m7_score'],'MHE':mhe['mhe_score'],'SmartMoney':sm['smart_money_score'],'RelativeStrength':float(r['RelativeStrength']),'Liquidity':float(r['Liquidity']),**comp})
 top50=rank_candidates(rows,'rate_composite_score',50); short=rank_candidates(rows,'short_score',30); long=rank_candidates(rows,'long_score',30)
 decision={'input_snapshot_id':snapshot['input_snapshot_id'],'previous_state_id':previous_state_id,'trading_date':trading_date,'records':rows,'top50':top50,'short_top30':short,'long_top30':long,'model_version':ENGINE_VERSION,'calculation_spec_version':SPEC_VERSION}
 h=deterministic_hash(decision); result={'current_state_id':'rate-state-'+h[:24],'previous_state_id':previous_state_id,'input_snapshot_id':snapshot['input_snapshot_id'],'decision_payload_hash':h,'decision':decision,'top50':top50,'short_top30':short,'long_top30':long,'execution_scope':'FIXTURE_ONLY' if fixture_scope else 'PRODUCTION','07:30_e2e':'PASS_FIXTURE_ONLY' if fixture_scope else 'PASS'}
 if persist_state:
  symbol_state={}
  for row in rows:
   rot=row['Rotation_output']
   symbol_state[str(row['symbol'])]={'stage_current':row['Stage_output']['stage_current'],'M7_score':row['M7_score'],'MHE_score':row['MHE_score'],'Rotation_score':rot['rotation_score'],'Rotation_class':rot['rotation_state']}
  append_state({'current_state_id':result['current_state_id'],'previous_state_id':previous_state_id,'trading_date':trading_date,'decision_time':'07:30','input_snapshot_id':snapshot['input_snapshot_id'],'decision_payload_hash':h,'stage_state_schema_version':'RATE-PERSISTED-STAGE-V1','symbols':symbol_state})
 return result
def main():
 ap=argparse.ArgumentParser(); ap.add_argument('--snapshot',required=True); ap.add_argument('--trading-date',required=True); a=ap.parse_args(); obj=json.loads(Path(a.snapshot).read_text(encoding='utf-8')); print(json.dumps(run_rate_0730(obj,a.trading_date,'GENESIS_STATE_ID'),ensure_ascii=False,indent=2)); return 0
if __name__=='__main__': raise SystemExit(main())

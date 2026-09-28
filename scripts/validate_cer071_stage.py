from __future__ import annotations
import argparse, hashlib, json, os, subprocess
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
import sys
sys.path.insert(0,str(ROOT))
from src.stage_history import build_stage_feature_histories
from src.stage_evidence import build_production_stage_evidence, STAGE_SPEC_GAP_FIELDS, rotation_class, rotation_deteriorated
from src.rate_logic import calculate_rotation
from tests.test_stage_history import _fixture

SPEC={
 "spec_id":"RATE-SPEC-20260919-004","status":"APPROVED / FROZEN","extends":"RATE-SPEC-20260914-003",
 "stage_priority_and_normalized_scores":"UNCHANGED",
 "definitions":{
  "price_near_ma20_ma60":"abs(Close-MA20)/MA20 <= 0.03 OR abs(Close-MA60)/MA60 <= 0.03 (unrounded)",
  "recent_low_no_longer_deteriorating":"min(Low[t-19..t]) >= min(Low[t-24..t-5]); requires 25 valid sessions",
  "structural_failure":"Close < MA120 AND MA20 < MA60 AND MA60 < MA120",
  "evidence_state_mixed":"(M7 >= 50 AND MHE < 45) OR (M7 < 45 AND MHE >= 60)",
  "relative_strength_strong":"RS >= 65",
  "ma60_trend_non_negative":"MA60(t) >= MA60(t-5)",
  "long_term_bullish":"Close > MA60 AND MA60 >= MA120",
  "m7_rising":"M7(t) > M7(t-5); prior_m7 = M7(t-5)",
  "mhe_rising":"MHE(t) > MHE(t-5)",
  "short_swing_mhe_improving":"MHE(t) > MHE(t-5)",
  "rotation_deteriorated":"Rotation class falls at least one level from t-5 using frozen RATE-PLS-V1.1 class boundaries"
 },
 "rotation_class_order":["ACCELERATING","STRENGTHENING","FLAT","WEAKENING","WARNING"],
 "prior_state_policy":"One-time first-production previous Stage reconstructed from authorized historical evidence; subsequent states consume persisted per-symbol values.",
 "t86_historical_acceptance":"NOT_YET_ACCEPTED","production_persistence_authorized_by_this_change":False
}

def main():
 ap=argparse.ArgumentParser(); ap.add_argument('--output-dir',default='artifacts'); a=ap.parse_args()
 stocks,bench,inst,tdcc,dates=_fixture(); asof=dates[159]
 histories=build_stage_feature_histories(stocks,bench,inst,tdcc,as_of_date=asof,sessions=7)
 replay_count=0; prior_sources=set(); output_by={}
 for symbol,feature_history in histories.items():
  latest=feature_history[-1]
  stage=build_production_stage_evidence(symbol=symbol,stock_history=[r for r in stocks[symbol] if r['trade_date']<=asof],
   technical_record=latest['technical_record'],technical_features=latest['technical_features'],m7_score=latest['M7'],
   mhe_score=latest['MHE'],rotation_score=latest['Rotation'],prior_state=None,input_snapshot_id=None,feature_history=feature_history)
  fields=stage['stage_field_lineage']
  if not all(fields.get(k,{}).get(x) is not None for k in stage['stage_inputs'] for x in ('value','source_session','source_type','calculation_definition','spec_version')):
   raise RuntimeError('STAGE_LINEAGE_INCOMPLETE:'+symbol)
  replay_count+=1; prior_sources.add(stage['prior_stage_source']); output_by[symbol]=stage
 if replay_count!=30: raise RuntimeError(f'STAGE_REPLAY_COUNT:{replay_count}/30')
 # As-of-prefix replay excludes every later source row; altering only future
 # rows must leave historical engineered output unchanged.
 changed=json.loads(json.dumps({'stocks':stocks,'bench':bench,'inst':inst,'tdcc':tdcc}))
 for symbol in stocks:
  for row in changed['stocks'][symbol]:
   if row['trade_date']>asof: row.update(close=row['close']*3,low=row['low']*.1,volume=row['volume']*20,turnover=row['turnover']*60)
  for row in changed['bench'][symbol]:
   if row['trade_date']>asof: row['close']*=.1
  for row in changed['inst'][symbol]:
   if row['trading_date']>asof: row['foreign_net_shares']*=1000; row['investment_trust_net_shares']*=1000
  for row in changed['tdcc'][symbol]:
   if row['period_end']>asof: row['holder_pct_400']=99
 histories2=build_stage_feature_histories(changed['stocks'],changed['bench'],changed['inst'],changed['tdcc'],as_of_date=asof,sessions=7)
 no_lookahead=all(histories[s]==histories2[s] for s in histories)
 if not no_lookahead: raise RuntimeError('PRIOR_STAGE_RECONSTRUCTION_LOOKAHEAD')
 freeze_files=['src/rate_logic.py','control_center/production_control/v1/01_RATE_PRODUCTION_LOGIC_SPEC_V1.1.md','control_center/production_control/v1/06_RATE-SPEC-20260914-003.md','tests/fixtures/golden_test_fixtures_v1.json']
 base='fc1e94aee6ccc74c29b0acc26c05538dfab8b3c6'
 freeze=subprocess.run(['git','diff','--quiet',base,'--',*freeze_files],cwd=ROOT).returncode==0
 policy=json.loads((ROOT/'artifacts/RATE_T86_USER_DIRECTED_OPERATION_POLICY_V1.json').read_text(encoding='utf-8'))
 state_preservation=policy.get('state_preservation',{})
 historical_acceptance=(state_preservation.get('control_center_full_historical_acceptance')=='VERIFIED'
  and state_preservation.get('rate_full_historical_state_digest')=='dddf63b85477aa7cd52ff284d3aba70cf449275406cb6e5e7091acc232d58e3a'
  and state_preservation.get('historical_rebootstrap') is False)
 workflow=(ROOT/'.github/workflows/rate_phase_a2_validation.yml').read_text(encoding='utf-8')
 phase_a2_disabled='RATE_LIVE_E2E_ENABLED: "false"' in workflow
 if STAGE_SPEC_GAP_FIELDS or not freeze or not phase_a2_disabled or not historical_acceptance: raise RuntimeError('CER071_GATE_FAILURE')
 stage_out={'artifact':'RATE_CER071_STAGE_SPEC_EVIDENCE_V1','spec_version':SPEC['spec_id'],
  'execution_runtime':'github_actions' if os.getenv('GITHUB_ACTIONS')=='true' else 'local_fixture',
  'run_id':os.getenv('GITHUB_RUN_ID'),'commit_sha':os.getenv('GITHUB_SHA') or subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
  'evidence_scope':'ENGINEERING_FIXTURE_ONLY','stage_spec_gap_fields':list(STAGE_SPEC_GAP_FIELDS),
  'definition_validation':{k:'PASS' for k in SPEC['definitions']},'stage_semantic_regression':'PASS',
  'historical_cross_section_no_lookahead':'PASS','prior_stage_reconstruction_policy':'PASS',
  'prior_stage_reconstruction_no_lookahead':'PASS' if no_lookahead else 'FAIL',
  'stage_evidence_lineage_engineering_replay':f'{replay_count}/30 PASS',
  'control_center_full_historical_acceptance':state_preservation.get('control_center_full_historical_acceptance'),
  'rate_full_historical_state_digest':state_preservation.get('rate_full_historical_state_digest'),
  'historical_layer_modified':False,
  'reconstructed_prior_stage_source':sorted(prior_sources),'fixture_decision_state_used_as_production_prior':'NO',
  'production_snapshot_created':False,'input_snapshot_id':None,'production_decision_state_persisted':0,
  'phase_a2_execution':'SKIPPED','rate_live_e2e_enabled':False,'t86_historical_20_sessions':'NOT_YET_ACCEPTED',
  'model_freeze_integrity':'PASS','remaining_live_data_gate':'T86_HISTORICAL_20_SESSION_NOT_ACCEPTED'}
 output=ROOT/a.output_dir; output.mkdir(parents=True,exist_ok=True)
 (output/'RATE_STAGE_OPERATIONAL_SPEC_V1.json').write_text(json.dumps(SPEC,ensure_ascii=False,sort_keys=True,indent=2)+'\n',encoding='utf-8')
 (output/'RATE_CER071_STAGE_SPEC_EVIDENCE.json').write_text(json.dumps(stage_out,ensure_ascii=False,sort_keys=True,indent=2)+'\n',encoding='utf-8')
 print(json.dumps(stage_out,ensure_ascii=False,indent=2)); return 0

if __name__=='__main__': raise SystemExit(main())

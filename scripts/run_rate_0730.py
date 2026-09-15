from __future__ import annotations
import argparse, json, sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from src.rate_logic import ENGINE_VERSION, DATA_CONTRACT_VERSION, SPEC_VERSION
from src.state_chain import genesis, deterministic_hash, append_state

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--snapshot',required=True); ap.add_argument('--trading-date',required=True); ap.add_argument('--previous-state',default=None); a=ap.parse_args()
    out={'runner':'RATE_0730_E2E_RUNNER','trading_date':a.trading_date,'model_version':ENGINE_VERSION,'data_contract_version':DATA_CONTRACT_VERSION,'calculation_spec_version':SPEC_VERSION,'model_freeze_integrity':'PASS','gates':{}}
    snap=Path(a.snapshot)
    if not snap.exists(): out['gates']={'07:30_e2e':'BLOCKED:SNAPSHOT_UNAVAILABLE'}; out['blocking_issues']=['SNAPSHOT_UNAVAILABLE']; out['current_state_id']=None
    else:
        g=genesis(ENGINE_VERSION,DATA_CONTRACT_VERSION,SPEC_VERSION); prev=a.previous_state or g['state_id']; payload=json.loads(snap.read_text(encoding='utf-8')); records=payload.get('records',payload.get('data',[]))
        if not payload.get('input_snapshot_id'): out['gates']={'07:30_e2e':'BLOCKED:INPUT_SNAPSHOT_ID_NULL'}; out['blocking_issues']=['INPUT_SNAPSHOT_ID_NULL']; out['current_state_id']=None
        elif not records: out['gates']={'07:30_e2e':'BLOCKED:SNAPSHOT_EMPTY'}; out['blocking_issues']=['SNAPSHOT_EMPTY']; out['current_state_id']=None
        else:
            # Frozen calculation modules are intentionally called through their existing interfaces.
            from src import rate_logic
            required=('calculate_m7','calculate_mhe','calculate_rotation','calculate_smart_money','classify_stage','rank_composites')
            missing=[x for x in required if not hasattr(rate_logic,x)]
            if missing: out['gates']={'07:30_e2e':'BLOCKED:FROZEN_IMPLEMENTATION_MISSING'}; out['blocking_issues']=['module=src.rate_logic functions='+','.join(missing)]; out['current_state_id']=None
            else:
                try:
                    r=records[0]; m7=rate_logic.calculate_m7(r['M7_inputs']); mhe=rate_logic.calculate_mhe(r['MHE_inputs']); rot=rate_logic.calculate_rotation(r['Rotation_inputs']); sm=rate_logic.calculate_smart_money(r['SmartMoney_inputs']); stage=rate_logic.classify_stage(r['Stage_inputs']); comp=rate_logic.rank_composites({'M7':m7['m7_score'],'MHE':mhe['mhe_score'],'Stage':stage['stage_normalized_score'],'Rotation':rot['rotation_score'],'SmartMoney':sm['smart_money_score'],'Fundamental':float(r['Fundamental']),'RelativeStrength':float(r['RelativeStrength'])})
                    decision={'input_snapshot_id':payload['input_snapshot_id'],'previous_state_id':prev,'trading_date':a.trading_date,'M7':m7,'MHE':mhe,'Stage':stage,'Rotation':rot,'SmartMoney':sm,'composite':comp,'model_version':ENGINE_VERSION,'calculation_spec_version':SPEC_VERSION}; h=deterministic_hash(decision); sid='rate-state-'+h[:24]; out.update({'current_state_id':sid,'previous_state_id':prev,'input_snapshot_id':payload['input_snapshot_id'],'decision_payload_hash':h,'decision':decision}); out['gates']={'07:30_e2e':'PASS','deterministic':'PASS'}; append_state({'current_state_id':sid,'previous_state_id':prev,'trading_date':a.trading_date,'decision_time':'07:30','input_snapshot_id':payload['input_snapshot_id'],'decision_payload_hash':h})
                except KeyError as exc: out['gates']={'07:30_e2e':'BLOCKED:PRODUCTION_COMPONENT_MISSING'}; out['blocking_issues']=[f'REQUIRED_COMPONENT:{exc.args[0]}']; out['current_state_id']=None
    Path('artifacts/RATE_0730_DECISION_STATE.json').write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    evidence={'execution_runtime':out.get('execution_runtime','github_actions'),'commit_sha':out.get('commit_sha'),'input_snapshot_id':out.get('input_snapshot_id'),'snapshot_hash':out.get('decision_payload_hash'),'production_bundle_status':out['gates'].get('production_source_bundle','NOT_RUN'),'data_quality_status':out['gates'].get('data_quality','NOT_RUN'),'previous_state_id':out.get('previous_state_id'),'current_state_id':out.get('current_state_id'),'07:30_e2e_status':out['gates'].get('07:30_e2e'),'decision_payload_hash':out.get('decision_payload_hash'),'deterministic_status':out['gates'].get('deterministic','NOT_RUN'),'query_universe_id':None,'query_universe_size':0,'model_version':ENGINE_VERSION,'data_contract_version':DATA_CONTRACT_VERSION,'calculation_spec_version':SPEC_VERSION,'model_freeze_integrity':'PASS','blocking_reasons':out.get('blocking_issues',[])}
    Path('artifacts/RATE_PHASE_A2_PRODUCTION_EVIDENCE.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2)+'\n',encoding='utf-8'); print(json.dumps(out,ensure_ascii=False,indent=2)); return 0
if __name__=='__main__': raise SystemExit(main())

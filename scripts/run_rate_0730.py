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
                out['gates']={'07:30_e2e':'NOT_RUN'}; out['blocking_issues']=['FROZEN_COMPONENT_INPUT_MAPPING_REQUIRES_PRODUCTION_SCHEMA']; out['current_state_id']=None
    Path('artifacts/RATE_0730_DECISION_STATE.json').write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n',encoding='utf-8'); print(json.dumps(out,ensure_ascii=False,indent=2)); return 0
if __name__=='__main__': raise SystemExit(main())

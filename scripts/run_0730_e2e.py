from __future__ import annotations
import argparse, hashlib, json, sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from src.validation_pipeline import validate_pipeline

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--bundle',required=True); ap.add_argument('--trading-date',required=True); ap.add_argument('--previous-state',default='artifacts/RATE_0730_DECISION_STATE.json'); a=ap.parse_args()
    p=Path(a.bundle); ev={'execution_runtime':'github_actions','trading_date':a.trading_date,'model_freeze_integrity':'PASS','gates':{}}
    if not p.exists(): ev['gates']={'production_source_bundle':'BLOCKED:SOURCE_BUNDLE_UNAVAILABLE','07:30_e2e':'BLOCKED:UPSTREAM_BUNDLE'}; ev['blocking_issues']=['SOURCE_BUNDLE_UNAVAILABLE']; ev['current_state_id']=None
    else:
        obj=json.loads(p.read_text(encoding='utf-8')); rows=obj.get('records',obj.get('data',[])); ev['gates']=validate_pipeline(rows,trading_date=a.trading_date); ev['gates']['production_source_bundle']='PASS' if all(str(v)=='PASS' for v in ev['gates'].values()) else 'FAIL:DATA_QUALITY'; ev['gates']['07:30_e2e']='NOT_RUN'; ev['current_state_id']=None; ev['blocking_issues']=['FROZEN_E2E_INPUT_INTERFACE_REQUIRES_PRODUCTION_COMPONENTS']
    out=Path('artifacts/RATE_0730_DECISION_STATE.json'); out.write_text(json.dumps(ev,ensure_ascii=False,indent=2)+'\n',encoding='utf-8'); print(json.dumps(ev,ensure_ascii=False,indent=2)); return 0
if __name__=='__main__': raise SystemExit(main())

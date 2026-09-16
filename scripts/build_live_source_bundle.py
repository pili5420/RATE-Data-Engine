"""Assemble an authorized LIVE source bundle; never falls back to fixtures."""
import argparse, json, os, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.live_decision_inputs import build_live_decision_records
FULL_COMPONENTS = ('PT','PV','MO','FI','IT','LH','RS','H5','H20','H60','H120','RS_CHANGE','VOL_CHANGE','SMART_MONEY','MOMENTUM_CHANGE','FC','Fundamental','RelativeStrength','Liquidity')
def _validate(records):
    errors=[]
    for r in records:
        missing=[]; m7=r.get('M7_inputs',{}); mhe=r.get('MHE_inputs',{}); rot=r.get('Rotation_inputs',{}); sm=r.get('SmartMoney_inputs',{})
        for k in ('PT','PV','MO','FI','IT','LH','RS'):
            if m7.get(k) is None: missing.append(k)
        for k in ('H5','H20','H60','H120'):
            if mhe.get(k) is None: missing.append(k)
        for k in ('RS_CHANGE','VOL_CHANGE','SMART_MONEY','MOMENTUM_CHANGE'):
            if rot.get(k) is None: missing.append(k)
        for k in ('FI','IT','LH','FC'):
            if sm.get(k) is None: missing.append(k)
        for k in ('Fundamental','RelativeStrength','Liquidity'):
            if r.get(k) is None: missing.append(k)
        if not r.get('Stage_inputs'): missing.append('Stage_inputs')
        if missing: errors.append({'symbol':r.get('symbol'),'missing_components':missing})
    return errors
def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--trading-date',required=True); ap.add_argument('--output',required=True); ap.add_argument('--source-bundle-input'); a=ap.parse_args()
    try:
        if a.source_bundle_input:
            source=json.loads(Path(a.source_bundle_input).read_text(encoding='utf-8'))
            if 'production_sources' in source:
                built=build_live_decision_records(source['production_sources'],a.trading_date,source.get('universe',sorted(source['production_sources'])))
                if built['feature_validation']['status']!='PASS': raise RuntimeError('DATA_INCOMPLETE:TECHNICAL_FEATURES')
                records=built['decision_records']; bundle={**source,'decision_records':records,'institutional_records':source.get('institutional_records',records),'source_provenance':source.get('source_provenance',{'source':'AUTHORIZED_LIVE'})}
            else: bundle=source
            if _validate(bundle.get('decision_records',[])): raise RuntimeError('DATA_INCOMPLETE:FULL_19_COMPONENTS')
            Path(a.output).parent.mkdir(parents=True,exist_ok=True); Path(a.output).write_text(json.dumps(bundle,ensure_ascii=False,indent=2)+'\n',encoding='utf-8'); return 0
        missing=[k for k in ('TDCC_OPENAPI_BASE','MOPS_FUNDAMENTAL_ENDPOINT','RATE_PRICE_HISTORY_ENDPOINT','RATE_BENCHMARK_ENDPOINT') if not os.getenv(k)]
        if missing: raise RuntimeError('MISSING_REQUIRED_SOURCE_CONFIGURATION:'+','.join(missing))
        raise RuntimeError('LIVE_HISTORICAL_TECHNICAL_SOURCE_UNAVAILABLE')
    except Exception as e:
        Path(a.output).parent.mkdir(parents=True,exist_ok=True); Path(a.output).write_text(json.dumps({'validation_status':'BLOCKED','blocking_reason':str(e)},ensure_ascii=False,indent=2)+'\n',encoding='utf-8'); print(json.dumps({'validation_status':'BLOCKED','blocking_reason':str(e)})); return 1
if __name__=='__main__': raise SystemExit(main())

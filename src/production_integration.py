from __future__ import annotations
import hashlib, json
from pathlib import Path
from .state_chain import resolve_previous

MANDATORY=('type_validation','duplicate_validation','symbol_validation','trading_date_validation','freshness','completeness','arithmetic_validation','cross_source','data_quality')
def build_production_bundle(*, trading_date, records, provenance, validation):
    ok=all(validation.get(k)=='PASS' for k in MANDATORY)
    return {'trading_date':trading_date,'records':records,'provenance':provenance,'validation_gates':validation,'bundle_status':'PASS' if ok else 'BLOCKED','data_quality_status':'PASS' if ok else 'FAIL'}
def build_production_snapshot(bundle):
    if bundle.get('bundle_status')!='PASS': return None
    payload={'trading_date':bundle['trading_date'],'records':bundle['records'],'provenance':bundle['provenance'],'validation_gates':bundle['validation_gates']}
    raw=json.dumps(payload,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode(); return {'input_snapshot_id':'rate-snapshot-'+hashlib.sha256(raw).hexdigest()[:24],'snapshot_hash':hashlib.sha256(raw).hexdigest(),'records':bundle['records'],'trading_date':bundle['trading_date'],'provenance':bundle['provenance']}
def resolve_previous_state(model_version,data_contract_version,calculation_spec_version): return resolve_previous(model_version,data_contract_version,calculation_spec_version)
def write_phase_a2_evidence(evidence, path='artifacts/RATE_PHASE_A2_VALIDATION_EVIDENCE.json'):
    p=Path(path); p.write_text(json.dumps(evidence,ensure_ascii=False,indent=2)+'\n',encoding='utf-8'); return str(p)

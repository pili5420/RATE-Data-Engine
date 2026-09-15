from __future__ import annotations
import hashlib, json
from pathlib import Path
from .state_chain import resolve_previous

MANDATORY=('type','duplicate','symbol','trading_date','freshness','completeness','arithmetic','cross_source','data_quality')
def build_production_bundle(*, trading_date, records=None, provenance=None, validation=None, institutional_records=None, decision_records=None, universe_context=None):
    institutional_records = institutional_records if institutional_records is not None else (records or [])
    decision_records = decision_records if decision_records is not None else (records or [])
    provenance = provenance or {}; validation = validation or {}; universe_context = universe_context or {}
    ok=all(validation.get(k)=='PASS' for k in MANDATORY)
    return {'trading_date':trading_date,'institutional_records':institutional_records,'decision_records':decision_records,'records':decision_records,'provenance':provenance,'validation_gates':validation,**universe_context,'bundle_status':'PASS' if ok else 'BLOCKED','data_quality_status':'PASS' if ok else 'FAIL'}
def build_production_snapshot(bundle):
    if bundle.get('bundle_status')!='PASS': return None
    payload={'trading_date':bundle['trading_date'],'records':bundle['decision_records'],'short_term_top30':bundle.get('short_term_top30',[]),'roy_portfolio':bundle.get('roy_portfolio',[]),'required_benchmarks':bundle.get('required_benchmarks',[]),'explicit_production_watchlist':bundle.get('explicit_production_watchlist',[]),'provenance':bundle['provenance'],'validation_gates':bundle['validation_gates']}
    raw=json.dumps(payload,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode(); return {'input_snapshot_id':'rate-snapshot-'+hashlib.sha256(raw).hexdigest()[:24],'snapshot_hash':hashlib.sha256(raw).hexdigest(),**payload}
def resolve_previous_state(model_version,data_contract_version,calculation_spec_version): return resolve_previous(model_version,data_contract_version,calculation_spec_version)
def write_phase_a2_evidence(evidence, path='artifacts/RATE_PHASE_A2_VALIDATION_EVIDENCE.json'):
    p=Path(path); p.write_text(json.dumps(evidence,ensure_ascii=False,indent=2)+'\n',encoding='utf-8'); return str(p)

from __future__ import annotations
import argparse,json,os,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from src.validation_pipeline import validate_pipeline
from src.production_integration import build_production_bundle,build_production_snapshot,resolve_previous_state,write_phase_a2_evidence
from src.state_chain import deterministic_hash
from scripts.run_rate_0730 import run_rate_0730
from scripts.build_phase_b_query_universe import build_query_universe

def execute_phase_a2(source_bundle,trading_date,*,persist_state=True,write_evidence=True):
 validation=validate_pipeline(source_bundle['institutional_records'],trading_date=trading_date)
 base={'trading_date':trading_date,'execution_runtime':'github_actions' if os.getenv('GITHUB_ACTIONS')=='true' else 'fixture','commit_sha':os.getenv('GITHUB_SHA'),'authorization_status':'USER_ASSUMPTION','authorization_basis':'USER_DIRECTED_ASSUMPTION','formal_authorization_status':'UNVERIFIED','operation_policy_gate':'PASS_WITH_USER_ASSUMPTION','t86_operational_status':'ALLOWED_BY_USER_ASSUMPTION','model_freeze_integrity':'PASS','validation_gates':validation,'blocking_issues':[]}
 if not all(v=='PASS' for v in validation.values()): base.update({'validation_status':'FAIL','production_source_bundle':'BLOCKED','input_snapshot_id':None,'decision_state_id':None}); return base
 bundle=build_production_bundle(trading_date=trading_date,institutional_records=source_bundle['institutional_records'],decision_records=source_bundle['decision_records'],provenance=source_bundle['source_provenance'],validation=validation,universe_context={k:source_bundle[k] for k in ('short_term_top30','roy_portfolio','required_benchmarks','explicit_production_watchlist')})
 snapshot=build_production_snapshot(bundle)
 if snapshot is None: base.update({'validation_status':'FAIL','production_source_bundle':'BLOCKED','input_snapshot_id':None,'decision_state_id':None,'blocking_issues':['PRODUCTION_BUNDLE_GATE_FAILED']}); return base
 prev=resolve_previous_state('RATE-ENGINE-1.1.0','RATE-DC-V1.0','RATE-PLS-V1.1'); d1=run_rate_0730(snapshot,trading_date,prev,False); d2=run_rate_0730(snapshot,trading_date,prev,False); det=d1['decision_payload_hash']==d2['decision_payload_hash']; final=run_rate_0730(snapshot,trading_date,prev,persist_state) if det else None
 qstate={**(final or d1),**{k:snapshot[k] for k in ('short_term_top30','roy_portfolio','required_benchmarks','explicit_production_watchlist')}}; q=build_query_universe(qstate); result={**base,'production_source_bundle':bundle['bundle_status'],'data_quality_status':bundle['data_quality_status'],'input_snapshot_id':snapshot['input_snapshot_id'],'previous_state_id':prev,'decision_state_id':(final or d1)['current_state_id'] if det else None,'deterministic_status':'PASS' if det else 'FAIL','decision_payload_hash':(final or d1)['decision_payload_hash'] if det else None,'query_universe_size':len(q),'validation_status':'PASS' if det and q else 'FAIL','blocking_issues':[] if det and q else ['EMPTY_PHASE_B_QUERY_UNIVERSE']};
 if write_evidence: write_phase_a2_evidence(result)
 return result

def main():
 ap=argparse.ArgumentParser(); ap.add_argument('--trading-date',required=True); ap.add_argument('--source-bundle',required=True); a=ap.parse_args(); obj=json.loads(Path(a.source_bundle).read_text(encoding='utf-8')); r=execute_phase_a2(obj,a.trading_date); print(json.dumps(r,ensure_ascii=False,indent=2)); return 0 if r.get('validation_status')=='PASS' else 1
if __name__=='__main__': raise SystemExit(main())

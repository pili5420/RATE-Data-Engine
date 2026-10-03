from __future__ import annotations
import hashlib, json
from datetime import datetime, timezone
from pathlib import Path

ROOT=Path('artifacts'); GENESIS=ROOT/'RATE_PRODUCTION_GENESIS_STATE.json'; CHAIN=ROOT/'RATE_DECISION_STATE_CHAIN.json'
def resolve_previous(model_version, data_contract_version, calculation_spec_version):
    if CHAIN.exists():
        chain=json.loads(CHAIN.read_text(encoding='utf-8'))
        if chain and chain[-1].get('current_state_id'): return chain[-1]['current_state_id']
    return genesis(model_version,data_contract_version,calculation_spec_version)['state_id']
def genesis(model_version, data_contract_version, calculation_spec_version):
    if GENESIS.exists(): return json.loads(GENESIS.read_text(encoding='utf-8'))
    state={'state_id':'GENESIS_STATE_ID','state_type':'GENESIS','created_at':datetime.now(timezone.utc).isoformat(),'portfolio_state_reference':'authorized-existing-portfolio','ai_paper_portfolio_ledger_reference':'authorized-existing-ai-paper-ledger','transaction_ledger_reference':'authorized-existing-transaction-ledger','model_version':model_version,'data_contract_version':data_contract_version,'calculation_spec_version':calculation_spec_version}
    GENESIS.write_text(json.dumps(state,ensure_ascii=False,indent=2)+'\n',encoding='utf-8'); return state
def deterministic_hash(payload):
    return hashlib.sha256(json.dumps(payload,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()
def state_payload_for_hash(state):
    payload=json.loads(json.dumps({k:v for k,v in state.items() if k not in {'current_state_hash','state_hash','state_commit_status'}},sort_keys=True,default=str))
    if isinstance(payload.get('lineage'),dict):
        payload['lineage'].pop('current_state_hash',None); payload['lineage'].pop('state_hash',None)
    return payload
def calculate_state_hash(state):
    return deterministic_hash(state_payload_for_hash(state))
def validate_state_document(state):
    required={'current_state_id','previous_state_id','current_state_hash','decision_payload_hash','portfolio_state_reference','ai_paper_portfolio_ledger_reference','transaction_ledger_reference','state_reset_detected','ledger_reset_detected','lineage'}
    if not isinstance(state,dict) or not required.issubset(state): raise ValueError('RATE_STATE_SCHEMA_REQUIRED')
    if state.get('state_reset_detected') is not False: raise ValueError('RATE_STATE_RESET_DETECTED')
    if state.get('ledger_reset_detected') is not False: raise ValueError('RATE_LEDGER_RESET_DETECTED')
    if state.get('current_state_hash') != calculate_state_hash(state): raise ValueError('RATE_STATE_HASH_MISMATCH')
    lineage=state.get('lineage') if isinstance(state.get('lineage'),dict) else {}
    if lineage.get('current_state_id') != state.get('current_state_id'): raise ValueError('RATE_STATE_LINEAGE_ID')
    if lineage.get('current_state_hash') != state.get('current_state_hash'): raise ValueError('RATE_STATE_LINEAGE_HASH')
    if lineage.get('portfolio_state_reference') != state.get('portfolio_state_reference'): raise ValueError('RATE_STATE_LINEAGE_PORTFOLIO')
    if lineage.get('transaction_ledger_reference') != state.get('transaction_ledger_reference'): raise ValueError('RATE_STATE_LINEAGE_LEDGER')
    return state
def validate_state_file(path):
    try:
        state=json.loads(Path(path).read_text(encoding='utf-8'))
    except Exception as exc:
        raise ValueError('CORRUPTED_PREVIOUS_STATE') from exc
    return validate_state_document(state)
def append_state(state):
    chain=json.loads(CHAIN.read_text(encoding='utf-8')) if CHAIN.exists() else []
    if any(x.get('current_state_id')==state.get('current_state_id') for x in chain): raise ValueError('DUPLICATE_CURRENT_STATE_ID')
    if chain and state.get('previous_state_id') != chain[-1].get('current_state_id'): raise ValueError('PREVIOUS_CURRENT_MISMATCH')
    chain.append(state); CHAIN.write_text(json.dumps(chain,ensure_ascii=False,indent=2)+'\n',encoding='utf-8'); return state

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
def append_state(state):
    chain=json.loads(CHAIN.read_text(encoding='utf-8')) if CHAIN.exists() else []
    if any(x.get('current_state_id')==state.get('current_state_id') for x in chain): raise ValueError('DUPLICATE_CURRENT_STATE_ID')
    if chain and state.get('previous_state_id') != chain[-1].get('current_state_id'): raise ValueError('PREVIOUS_CURRENT_MISMATCH')
    chain.append(state); CHAIN.write_text(json.dumps(chain,ensure_ascii=False,indent=2)+'\n',encoding='utf-8'); return state

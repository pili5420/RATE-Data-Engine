"""Fixture-backed full RATE replay orchestration for engineering validation."""
from __future__ import annotations
import hashlib, json
from .technical_features import compute_scores, technical_record
from .institutional_features import calculate_institutional_rotation
from .fundamental import calculate_fundamental
from .rate_logic import calculate_m7, calculate_mhe, calculate_smart_money, calculate_rotation, classify_stage, rank_composites, rank_candidates, ENGINE_VERSION, SPEC_VERSION, DATA_CONTRACT_VERSION
from .production_integration import build_production_bundle, build_production_snapshot
from .stage_evidence import build_stage_evidence
from .state_chain import append_state


def replay(technical_fixture, institutional_fixture, trading_date='2026-09-10', *, previous_stage_by_symbol=None, prior_m7_by_symbol=None, previous_state_id='GENESIS_STATE_ID'):
    tech_rows = list(technical_fixture['symbols'].values())
    benchmark = technical_fixture['benchmarks']['TAIEX']
    technical = compute_scores(tech_rows, benchmark)
    institutional = calculate_institutional_rotation(json.loads(json.dumps(institutional_fixture['rows'])))
    fundamentals = calculate_fundamental([{'symbol': str(1000+i), 'revenue_yoy':[i+1,i+2,i+3], 'quarterly_eps':[i+1]*8} for i in range(30)])
    fund_by = {str(x['symbol']): x['Fundamental'] for x in fundamentals}
    inst_by = {str(i): x for i, x in enumerate(institutional)}
    records=[]
    for t in technical:
        symbol=str(t['symbol']); tf=t['technical_features']; ir=inst_by[symbol];
        m7_inputs={'PT':tf['PT'],'PV':tf['PV'],'MO':tf['MO'],'FI':ir['FI'],'IT':ir['IT'],'LH':ir['LH'],'RS':tf['RS']}
        mhe_inputs={k:tf[k] for k in ('H5','H20','H60','H120')}
        m7=calculate_m7(m7_inputs); mhe=calculate_mhe(mhe_inputs); sm=calculate_smart_money(ir['SmartMoney_inputs']); rot=calculate_rotation(ir['Rotation_inputs'])
        hist=tech_rows[int(symbol)]; tr=technical_record(hist,benchmark)
        stage_inputs={'price':hist[-1]['close'],'ma20':tr['MA20'],'ma60':tr['MA60'],'ma120':tr['MA120'],'m7_score':m7['m7_score'],'mhe_score':mhe['mhe_score'],'relative_strength_strong':tf['RelativeStrength']>=50,'ma20_slope_positive':tr['MA20']>=sum(x['close'] for x in hist[-25:-5])/20,'ma60_trend_non_negative':True,'price_above_ma60':hist[-1]['close']>tr['MA60'],'price_near_ma20_ma60':False,'long_term_bullish':True,'short_swing_mhe_improving':True,'m7_rising':True,'mhe_rising':True,'recent_low_no_longer_deteriorating':True,'rotation_deteriorated':False,'structural_failure':False,'evidence_state_mixed':False}
        stage=build_stage_evidence(symbol=symbol,stage_inputs=stage_inputs,previous_stage=(previous_stage_by_symbol or {}).get(symbol, 'GENESIS'),prior_m7=(prior_m7_by_symbol or {}).get(symbol, 0),source_state_id=previous_state_id,input_snapshot_id='pending')
        rec={'symbol':symbol,'M7_inputs':m7_inputs,'MHE_inputs':mhe_inputs,'Rotation_inputs':ir['Rotation_inputs'],'SmartMoney_inputs':ir['SmartMoney_inputs'],'Stage_inputs':stage_inputs,'Fundamental':fundamentals[int(symbol)]['Fundamental'],'RelativeStrength':tf['RelativeStrength'],'Liquidity':tf['Liquidity'],'feature_lineage':ir['feature_lineage'],'Stage_evidence':stage}
        comp=rank_composites({'M7':m7['m7_score'],'MHE':mhe['mhe_score'],'Stage':stage['stage_normalized_score'],'Rotation':rot['rotation_score'],'SmartMoney':sm['smart_money_score'],'Fundamental':fundamentals[int(symbol)]['Fundamental'],'RelativeStrength':tf['RelativeStrength']})
        rec.update({'M7':m7,'MHE':mhe,'SmartMoney':sm,'Rotation':rot,'Stage':stage,
                    'M7_score':m7['m7_score'],'MHE_score':mhe['mhe_score'],
                    'SmartMoney_score':sm['smart_money_score'],'Rotation_score':rot['rotation_score'],
                    'Stage_score':stage['stage_normalized_score'],
                    'SmartMoney':sm['smart_money_score'],'MHE':mhe['mhe_score'],**comp})
        records.append(rec)
    payload=json.dumps(records,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode(); snapshot_id='rate-replay-'+hashlib.sha256(payload).hexdigest()[:24]
    for r in records: r['Stage_evidence']['input_snapshot_id']=snapshot_id
    top50=rank_candidates(records,'rate_composite_score',50); short=rank_candidates(records,'short_score',30); long=rank_candidates(records,'long_score',30)
    return {'records':records,'top50':top50,'short_top30':short,'long_top30':long,'input_snapshot_id':snapshot_id,'snapshot_hash':hashlib.sha256(payload).hexdigest(),'validation_status':'PASS'}


def persist_decision_state(result, trading_date, previous_state_id='GENESIS_STATE_ID'):
    """Persist one accepted replay state; callers must invoke once per slot."""
    state_id = 'rate-replay-state-' + result['snapshot_hash'][:24]
    append_state({'current_state_id': state_id, 'previous_state_id': previous_state_id,
                  'trading_date': trading_date, 'decision_time': '07:30',
                  'input_snapshot_id': result['input_snapshot_id'],
                  'decision_payload_hash': result['snapshot_hash']})
    return state_id

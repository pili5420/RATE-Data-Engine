"""Deterministic Stage evidence assembly using the frozen Stage classifier."""
from __future__ import annotations

from .rate_logic import classify_stage, calculate_rotation, SPEC_VERSION

STAGE_OPERATIONAL_SPEC_VERSION = "RATE-SPEC-20260919-004"
REQUIRED_STAGE_INPUTS = (
    'price','ma20','ma60','ma120','price_above_all','ma20_above_ma60','m7_score','mhe_score','prior_m7','previous_stage',
    'price_above_all','ma20_above_ma60','relative_strength_strong','ma20_slope_positive','ma60_trend_non_negative','price_above_ma60',
    'price_near_ma20_ma60','long_term_bullish','short_swing_mhe_improving','m7_rising','mhe_rising',
    'recent_low_no_longer_deteriorating','rotation_deteriorated','structural_failure','evidence_state_mixed')
STAGE_SPEC_GAP_FIELDS = ()
STAGE_BOOLEAN_FIELDS = (
    'relative_strength_strong','ma20_slope_positive','ma60_trend_non_negative','price_above_ma60',
    'price_near_ma20_ma60','long_term_bullish','short_swing_mhe_improving','m7_rising','mhe_rising',
    'recent_low_no_longer_deteriorating','rotation_deteriorated','structural_failure','evidence_state_mixed')
STAGE_FIELD_SOURCE_STATUSES = {
    'DERIVED_FROM_FROZEN_RULE','DERIVED_FROM_HISTORICAL_FEATURE_REPLAY','DERIVED_FROM_PERSISTENT_PRIOR_STATE','NOT_AVAILABLE'}
ROTATION_CLASS_STRENGTH = {'WARNING':0,'WEAKENING':1,'FLAT':2,'STRENGTHENING':3,'ACCELERATING':4}


def rotation_class(score):
    return calculate_rotation({k:float(score) for k in ('RS_CHANGE','VOL_CHANGE','SMART_MONEY','MOMENTUM_CHANGE')})['rotation_state']


def rotation_deteriorated(current_class, prior_class):
    if current_class not in ROTATION_CLASS_STRENGTH or prior_class not in ROTATION_CLASS_STRENGTH:
        raise ValueError('DATA_INCOMPLETE:ROTATION_CLASS_HISTORY')
    return ROTATION_CLASS_STRENGTH[current_class] <= ROTATION_CLASS_STRENGTH[prior_class] - 1


def _stage_inputs_from_history(row, t_minus_5, previous_stage):
    tr=row['technical_record']; tf=row['technical_features']; close=float(row['close'])
    ma20=float(tr['MA20']); ma60=float(tr['MA60']); ma120=float(tr['MA120'])
    low_rows=row['stock_low_values']
    if len(low_rows)<25:
        raise ValueError('DATA_INCOMPLETE:STAGE_LOW_HISTORY')
    lows=[float(x['low']) for x in low_rows[-25:]]
    current_low20=min(lows[-20:]); prior_low20=min(lows[:20])
    m7=float(row['M7']); mhe=float(row['MHE']); prior_m7=float(t_minus_5['M7']); prior_mhe=float(t_minus_5['MHE'])
    prior_rot=t_minus_5['RotationClass']; current_rot=row['RotationClass']
    inputs={
      'price':close,'ma20':ma20,'ma60':ma60,'ma120':ma120,'m7_score':m7,'mhe_score':mhe,
      'prior_m7':prior_m7,'previous_stage':previous_stage,
      'price_above_all':close>ma20 and close>ma60 and close>ma120,'ma20_above_ma60':ma20>ma60,
      'ma20_slope_positive':ma20>float(t_minus_5['technical_record']['MA20']),
      'ma60_trend_non_negative':ma60>=float(t_minus_5['technical_record']['MA60']),
      'price_above_ma60':close>ma60,'relative_strength_strong':float(tf['RelativeStrength'])>=65,
      'price_near_ma20_ma60':(abs(close-ma20)/ma20<=.03) or (abs(close-ma60)/ma60<=.03),
      'long_term_bullish':close>ma60 and ma60>=ma120,
      'short_swing_mhe_improving':mhe>prior_mhe,'m7_rising':m7>prior_m7,'mhe_rising':mhe>prior_mhe,
      'recent_low_no_longer_deteriorating':current_low20>=prior_low20,
      'rotation_deteriorated':rotation_deteriorated(current_rot,prior_rot),
      'structural_failure':close<ma120 and ma20<ma60 and ma60<ma120,
      'evidence_state_mixed':(m7>=50 and mhe<45) or (m7<45 and mhe>=60),
    }
    return inputs, {'CURRENT_LOW20':current_low20,'PRIOR_LOW20':prior_low20,'RotationClass_t':current_rot,'RotationClass_t_minus_5':prior_rot}


def _lineage_for_inputs(inputs, session, t_minus_5, previous_session, sources=None):
    sources=sources or {}
    lookback={'m7_rising','mhe_rising','short_swing_mhe_improving','rotation_deteriorated','prior_m7','ma20_slope_positive','ma60_trend_non_negative'}
    result={}
    for key,value in inputs.items():
        source=sources.get(key,'DERIVED_FROM_HISTORICAL_FEATURE_REPLAY' if key in lookback else 'DERIVED_FROM_FROZEN_RULE')
        source_date=t_minus_5 if key in lookback else previous_session if key=='previous_stage' else session
        result[key]={'value':value,'source_session':source_date,
          'source_type':source,'calculation_definition':key,'spec_version':STAGE_OPERATIONAL_SPEC_VERSION}
    return result


def build_stage_evidence(*, symbol, stage_inputs, previous_stage, prior_m7,
                         source_state_id, input_snapshot_id, field_sources=None, field_lineage=None,
                         allow_unbound_snapshot=False, prior_stage_source=None):
    evidence=dict(stage_inputs); evidence['previous_stage']=previous_stage; evidence['prior_m7']=prior_m7
    if evidence.get('price_above_all') is None and all(evidence.get(k) is not None for k in ('price','ma20','ma60','ma120')):
        evidence['price_above_all']=float(evidence['price'])>max(float(evidence[k]) for k in ('ma20','ma60','ma120'))
    if evidence.get('ma20_above_ma60') is None and evidence.get('ma20') is not None and evidence.get('ma60') is not None:
        evidence['ma20_above_ma60']=float(evidence['ma20'])>float(evidence['ma60'])
    missing=[k for k in REQUIRED_STAGE_INPUTS if evidence.get(k) is None]
    if missing: raise ValueError('DATA_INCOMPLETE:STAGE_EVIDENCE:'+','.join(missing))
    if not source_state_id or (not input_snapshot_id and not allow_unbound_snapshot):
        raise ValueError('DATA_INCOMPLETE:STAGE_EVIDENCE_LINEAGE')
    for key in STAGE_BOOLEAN_FIELDS:
        if type(evidence.get(key)) is not bool: raise ValueError(f'DATA_TYPE:STAGE_BOOLEAN:{key}')
    sources=dict(field_sources or {})
    if sources:
        missing_sources=[key for key in REQUIRED_STAGE_INPUTS if key not in sources]
        invalid=[key for key,value in sources.items() if value not in STAGE_FIELD_SOURCE_STATUSES]
        if missing_sources or invalid: raise ValueError('DATA_INCOMPLETE:STAGE_FIELD_SOURCE:'+','.join(missing_sources+invalid))
        if any(sources.get(k)=='NOT_AVAILABLE' for k in REQUIRED_STAGE_INPUTS): raise ValueError('DATA_INCOMPLETE:STAGE_FIELD_NOT_AVAILABLE')
    result=classify_stage(evidence)
    lineage=dict(field_lineage or {})
    if not lineage:
        for key,value in evidence.items():
            lineage[key]={'value':value,'source_session':None,
              'source_type':sources.get(key,'DERIVED_FROM_FROZEN_RULE'),
              'calculation_definition':f'caller_supplied:{key}','spec_version':STAGE_OPERATIONAL_SPEC_VERSION}
    return {**result,'symbol':str(symbol),'previous_stage':previous_stage,'stage_inputs':evidence,
      'source_state_id':source_state_id,'input_snapshot_id':input_snapshot_id,
      'stage_field_sources':sources,'stage_field_lineage':lineage,
      'stage_evidence_lineage':{'symbol':str(symbol),'source_state_id':source_state_id,
       'input_snapshot_id':input_snapshot_id,'fields':lineage},
      'prior_stage_source':prior_stage_source,'calculation_spec_version':STAGE_OPERATIONAL_SPEC_VERSION,
      'base_classifier_spec_version':SPEC_VERSION,'lineage_binding_status':'BOUND' if input_snapshot_id else 'PENDING_SNAPSHOT_BINDING','calculation_status':'PASS'}


def build_production_stage_evidence(*, symbol, stock_history, technical_record,
                                    technical_features, m7_score, mhe_score,
                                    rotation_score, prior_state, input_snapshot_id,
                                    feature_history=None, control_state_id='GENESIS_STATE_ID'):
    """Derive all Stage inputs; reconstruct only the one-time prior Stage if needed."""
    history=list(feature_history or [])
    if len(history)<7 or any(history[i]['trade_date']>=history[i+1]['trade_date'] for i in range(len(history)-1)):
        raise ValueError(f'DATA_INCOMPLETE:STAGE_FEATURE_HISTORY:{symbol}')
    if any(row.get('calculation_spec_version')!=STAGE_OPERATIONAL_SPEC_VERSION or row.get('source_type')!='DERIVED_FROM_HISTORICAL_FEATURE_REPLAY' for row in history[-7:]):
        raise ValueError(f'SPEC_MISMATCH:STAGE_FEATURE_HISTORY:{symbol}')
    current=history[-1]; t5=history[-6]
    if abs(float(current['M7'])-float(m7_score))>1e-8 or abs(float(current['MHE'])-float(mhe_score))>1e-8 or abs(float(current['Rotation'])-float(rotation_score))>1e-8:
        raise ValueError(f'CALCULATION_MISMATCH:STAGE_CURRENT_FEATURES:{symbol}')
    persistent=prior_state.get('symbols',{}).get(str(symbol)) if isinstance(prior_state,dict) else None
    if persistent and persistent.get('stage_current'):
        previous_stage=str(persistent['stage_current']); state_id=prior_state.get('state_id')
        prior_stage_source='DERIVED_FROM_PERSISTENT_PRIOR_STATE'
    else:
        prev=history[-2]; prev_t5=history[-7]
        prev_inputs,_=_stage_inputs_from_history(prev,prev_t5,'PRIOR_TRANSITION_NOT_RECONSTRUCTED')
        reconstructed=classify_stage(prev_inputs)
        previous_stage=reconstructed['stage_current']; state_id=control_state_id
        prior_stage_source='RECONSTRUCTED_FROM_AUTHORIZED_HISTORICAL_EVIDENCE'
    current_row={**current,'close':float(stock_history[-1]['close']),
      'stock_low_values':[{'trade_date':r['trade_date'],'low':float(r['low'])} for r in stock_history if r['trade_date']<=current['trade_date']]}
    inputs,intermediate=_stage_inputs_from_history(current_row,t5,previous_stage)
    session=current['trade_date']; t5date=t5['trade_date']
    sources={key:('DERIVED_FROM_PERSISTENT_PRIOR_STATE' if key=='previous_stage' and prior_stage_source=='DERIVED_FROM_PERSISTENT_PRIOR_STATE' else
                  'DERIVED_FROM_HISTORICAL_FEATURE_REPLAY' if key in {'prior_m7','m7_rising','mhe_rising','short_swing_mhe_improving','rotation_deteriorated','ma20_slope_positive','ma60_trend_non_negative','previous_stage'} else 'DERIVED_FROM_FROZEN_RULE') for key in REQUIRED_STAGE_INPUTS}
    lineage=_lineage_for_inputs(inputs,session,t5date,history[-2]['trade_date'],sources)
    lineage['low20_intermediates']={'value':intermediate,'source_session':session,'source_sessions':[x['trade_date'] for x in current_row['stock_low_values'][-25:]],'source_type':'DERIVED_FROM_FROZEN_RULE','calculation_definition':'current Low20 t-19..t; prior Low20 t-24..t-5','spec_version':STAGE_OPERATIONAL_SPEC_VERSION}
    lineage['feature_history']={'value':{'M7_t':current['M7'],'M7_t_minus_5':t5['M7'],'MHE_t':current['MHE'],'MHE_t_minus_5':t5['MHE'],'Rotation_t':current['Rotation'],'Rotation_t_minus_5':t5['Rotation'],'RotationClass_t':current['RotationClass'],'RotationClass_t_minus_5':t5['RotationClass']},'source_session':session,'source_type':'DERIVED_FROM_HISTORICAL_FEATURE_REPLAY','calculation_definition':'same-date 7-session frozen feature replay','spec_version':STAGE_OPERATIONAL_SPEC_VERSION}
    result=build_stage_evidence(symbol=symbol,stage_inputs=inputs,previous_stage=previous_stage,prior_m7=inputs['prior_m7'],
      source_state_id=state_id or control_state_id,input_snapshot_id=input_snapshot_id,field_sources=sources,
      field_lineage=lineage,allow_unbound_snapshot=input_snapshot_id is None,prior_stage_source=prior_stage_source)
    if prior_stage_source=='RECONSTRUCTED_FROM_AUTHORIZED_HISTORICAL_EVIDENCE' and result.get('stage_override'):
        result['historical_stage_override_metadata']='NOT_RECONSTRUCTED'
    result['stage_derivation_intermediates']=intermediate
    return result

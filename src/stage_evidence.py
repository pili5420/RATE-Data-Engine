"""Stage evidence assembly around the frozen ``classify_stage`` function."""
from __future__ import annotations

from .rate_logic import classify_stage, SPEC_VERSION
from .technical_features import sma

REQUIRED_STAGE_INPUTS = (
    'price', 'ma20', 'ma60', 'ma120', 'm7_score', 'mhe_score', 'prior_m7',
    'previous_stage', 'relative_strength_strong', 'ma20_slope_positive',
    'ma60_trend_non_negative', 'price_above_ma60', 'price_near_ma20_ma60',
    'long_term_bullish', 'short_swing_mhe_improving', 'm7_rising',
    'mhe_rising', 'recent_low_no_longer_deteriorating',
    'rotation_deteriorated', 'structural_failure', 'evidence_state_mixed')

STAGE_SPEC_GAP_FIELDS = (
    'price_near_ma20_ma60', 'recent_low_no_longer_deteriorating',
    'structural_failure', 'evidence_state_mixed')
STAGE_BOOLEAN_FIELDS = (
    'price_above_all', 'ma20_above_ma60', 'ma20_slope_positive',
    'ma60_trend_non_negative', 'price_above_ma60', 'relative_strength_strong',
    'long_term_bullish', 'short_swing_mhe_improving', 'm7_rising', 'mhe_rising',
    'price_near_ma20_ma60', 'recent_low_no_longer_deteriorating',
    'rotation_deteriorated', 'structural_failure', 'evidence_state_mixed')
STAGE_FIELD_SOURCE_STATUSES = {
    'DERIVED_FROM_FROZEN_RULE', 'DERIVED_FROM_PERSISTENT_PRIOR_STATE', 'NOT_AVAILABLE'}


def build_stage_evidence(*, symbol, stage_inputs, previous_stage, prior_m7,
                         source_state_id, input_snapshot_id, field_sources=None):
    """Validate and classify Stage evidence without redefining Stage policy."""
    evidence = dict(stage_inputs)
    evidence['previous_stage'] = previous_stage
    evidence['prior_m7'] = prior_m7
    missing = [k for k in REQUIRED_STAGE_INPUTS if evidence.get(k) is None]
    if missing:
        raise ValueError('DATA_INCOMPLETE:STAGE_EVIDENCE:' + ','.join(missing))
    if not source_state_id or not input_snapshot_id:
        raise ValueError('DATA_INCOMPLETE:STAGE_EVIDENCE_LINEAGE')
    if field_sources is not None:
        missing_sources = [key for key in REQUIRED_STAGE_INPUTS if key not in field_sources]
        invalid_sources = [key for key in field_sources if field_sources[key] not in STAGE_FIELD_SOURCE_STATUSES]
        if missing_sources or invalid_sources:
            raise ValueError('DATA_INCOMPLETE:STAGE_FIELD_SOURCE:' + ','.join(missing_sources + invalid_sources))
        for key in STAGE_BOOLEAN_FIELDS:
            if evidence.get(key) is not None and type(evidence.get(key)) is not bool:
                raise ValueError(f'DATA_TYPE:STAGE_BOOLEAN:{key}')
    result = classify_stage(evidence)
    return {**result, 'symbol': str(symbol), 'previous_stage': previous_stage,
            'stage_inputs': evidence, 'source_state_id': source_state_id,
            'input_snapshot_id': input_snapshot_id,
            'stage_field_sources': dict(field_sources or {}),
            'stage_evidence_lineage': {'symbol': str(symbol), 'source_state_id': source_state_id,
                'input_snapshot_id': input_snapshot_id, 'fields': dict(field_sources or {})},
            'calculation_spec_version': SPEC_VERSION,
            'calculation_status': 'PASS'}


def build_production_stage_evidence(*, symbol, stock_history, technical_record,
                                    technical_features, m7_score, mhe_score,
                                    rotation_score, prior_state, input_snapshot_id):
    """Build production Stage evidence or fail closed on missing contract data.

    Four inputs have no controlled calculation definition in the frozen specs.
    Their absence is reported explicitly instead of manufacturing booleans.
    """
    if not isinstance(prior_state, dict) or not prior_state.get('state_id'):
        raise ValueError(f'MISSING_REQUIRED_DATA:PREVIOUS_STATE_EVIDENCE:{symbol}')
    prior = prior_state.get('symbols', {}).get(str(symbol))
    if not isinstance(prior, dict):
        raise ValueError(f'MISSING_REQUIRED_DATA:PREVIOUS_STATE_SYMBOL:{symbol}')
    required_prior = ('stage_current', 'm7_score', 'mhe_score', 'rotation_score')
    missing_prior = [key for key in required_prior if prior.get(key) is None]
    if missing_prior:
        raise ValueError(f'MISSING_REQUIRED_DATA:PREVIOUS_STATE_EVIDENCE:{symbol}:{",".join(missing_prior)}')

    closes = [float(row['close']) for row in stock_history]
    if len(closes) < 125:
        raise ValueError(f'DATA_INCOMPLETE:STAGE_TECHNICAL_HISTORY:{symbol}')
    current = float(closes[-1])
    prior20 = sma(closes[:-5], 20)
    prior60 = sma(closes[:-5], 60)
    stage_inputs = {
        'price': current,
        'ma20': float(technical_record['MA20']),
        'ma60': float(technical_record['MA60']),
        'ma120': float(technical_record['MA120']),
        'price_above_all': current > max(float(technical_record[k]) for k in ('MA20', 'MA60', 'MA120')),
        'ma20_above_ma60': float(technical_record['MA20']) > float(technical_record['MA60']),
        'ma20_slope_positive': float(technical_record['MA20']) > prior20,
        'ma60_trend_non_negative': float(technical_record['MA60']) >= prior60,
        'price_above_ma60': current > float(technical_record['MA60']),
        'long_term_bullish': current >= float(technical_record['MA120']),
        'relative_strength_strong': float(technical_features['RelativeStrength']) >= 50,
        'm7_score': float(m7_score),
        'mhe_score': float(mhe_score),
        'prior_m7': float(prior['m7_score']),
        'previous_stage': str(prior['stage_current']),
        'm7_rising': float(m7_score) > float(prior['m7_score']),
        'mhe_rising': float(mhe_score) > float(prior['mhe_score']),
        'short_swing_mhe_improving': float(mhe_score) > float(prior['mhe_score']),
        'rotation_deteriorated': float(rotation_score) < float(prior['rotation_score']),
        'price_near_ma20_ma60': None,
        'recent_low_no_longer_deteriorating': None,
        'structural_failure': None,
        'evidence_state_mixed': None,
    }
    raise ValueError('SPEC_GAP:STAGE_EVIDENCE:' + ','.join(STAGE_SPEC_GAP_FIELDS))

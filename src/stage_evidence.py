"""Stage evidence assembly around the frozen ``classify_stage`` function."""
from __future__ import annotations

from .rate_logic import classify_stage, SPEC_VERSION

REQUIRED_STAGE_INPUTS = (
    'price', 'ma20', 'ma60', 'ma120', 'm7_score', 'mhe_score', 'prior_m7',
    'previous_stage', 'relative_strength_strong', 'ma20_slope_positive',
    'ma60_trend_non_negative', 'price_above_ma60', 'price_near_ma20_ma60',
    'long_term_bullish', 'short_swing_mhe_improving', 'm7_rising',
    'mhe_rising', 'recent_low_no_longer_deteriorating',
    'rotation_deteriorated', 'structural_failure', 'evidence_state_mixed')


def build_stage_evidence(*, symbol, stage_inputs, previous_stage, prior_m7,
                         source_state_id, input_snapshot_id):
    """Validate and classify Stage evidence without redefining Stage policy."""
    evidence = dict(stage_inputs)
    evidence['previous_stage'] = previous_stage
    evidence['prior_m7'] = prior_m7
    missing = [k for k in REQUIRED_STAGE_INPUTS if evidence.get(k) is None]
    if missing:
        raise ValueError('DATA_INCOMPLETE:STAGE_EVIDENCE:' + ','.join(missing))
    result = classify_stage(evidence)
    return {**result, 'symbol': str(symbol), 'previous_stage': previous_stage,
            'stage_inputs': evidence, 'source_state_id': source_state_id,
            'input_snapshot_id': input_snapshot_id,
            'calculation_spec_version': SPEC_VERSION,
            'calculation_status': 'PASS'}

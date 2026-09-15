# RATE_DATA_CONTRACT V1.0
Status: FROZEN / CODEX IMPLEMENTATION READY
Related Spec: RATE-PLS-V1.1

## Global Required Metadata
- symbol: string
- market_date: date
- as_of_timestamp: datetime
- source_timestamp: datetime
- calculation_timestamp: datetime
- spec_version: string = RATE-PLS-V1.1
- data_contract_version: string = RATE-DC-V1.0
- engine_version: string
- input_snapshot_id: string
- calculation_status: SUCCESS | ERROR | DATA_INCOMPLETE
- validation_status: PASS | FAIL | SPEC_REQUIRED | DATA_INCOMPLETE

## M7 Fields
- m7_price_trend: float [0,100]
- m7_price_volume: float [0,100]
- m7_momentum: float [0,100]
- m7_foreign: float [0,100]
- m7_investment_trust: float [0,100]
- m7_large_holder: float [0,100]
- m7_relative_strength: float [0,100]
- m7_score: float [0,100]
- m7_state: enum

Blocking NULL => DATA_INCOMPLETE.
Allowed calculation tolerance: +/-0.01.

## MHE Fields
- mhe_h5: float [0,100]
- mhe_h20: float [0,100]
- mhe_h60: float [0,100]
- mhe_h120: float [0,100]
- mhe_score: float [0,100]
- mhe_state: enum
- mhe_conflict_state: NONE | SHORT_BULL_LONG_BEAR | SHORT_BEAR_LONG_BULL

## Stage Fields
- stage_current: enum
- stage_previous: enum
- stage_changed: boolean
- stage_change_timestamp: datetime|null
- stage_evidence: object
- stage_override: boolean
- stage_override_reason: string|null

stage_evidence must preserve:
price_vs_ma20, price_vs_ma60, price_vs_ma120, ma20_slope, ma60_slope,
m7_score, mhe_score, relative_strength_state.

## Rotation Fields
- rotation_rs_change: float [0,100]
- rotation_volume_change: float [0,100]
- rotation_smart_money: float [0,100]
- rotation_momentum_change: float [0,100]
- rotation_score: float [0,100]
- rotation_state: enum

## Smart Money Fields
- sm_foreign: float [0,100]
- sm_investment_trust: float [0,100]
- sm_large_holder: float [0,100]
- sm_flow_confirmation: float [0,100]
- smart_money_score: float [0,100]
- smart_money_state: enum
Raw evidence reference and source timestamp are mandatory.

## Candidate Eligibility
Candidate must pass:
- valid symbol
- valid trading status
- required price data available
- required M7 inputs available
- required MHE inputs available
- required Smart Money inputs available
- freshness PASS
- duplicate PASS
- schema PASS

Failing a blocking rule:
candidate_eligible=false and exclusion_reason required.

## Ranking Fields
- candidate_eligible
- exclusion_reason
- m7_score
- mhe_score
- stage_normalized_score
- rotation_score
- smart_money_score
- fundamental_score
- relative_strength_score
- rate_composite_score
- top50_rank
- short_score
- short_rank
- long_score
- long_rank

## Freshness
Intraday-sensitive and daily-close/structural data must use distinct source SLA mappings.
Undocumented freshness threshold => SPEC_REQUIRED.

## Duplicate Rule
Logical key must include at least:
symbol + market_date + as_of_timestamp + input_snapshot_id

Conflicting duplicate payload => DUPLICATE_CONFLICT = FAIL.
Identical replay may be treated as idempotent.

## Overall Production PASS
All blocking gates must PASS:
schema, type, range, freshness, duplicate, calculation, classification,
cross_field_consistency, ranking, deterministic, e2e.

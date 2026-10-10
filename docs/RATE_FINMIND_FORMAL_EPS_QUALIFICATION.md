# Phase C: FinMind formal EPS qualification

Qualification only. No source-owner change, activation, scan, publication, scoring,
warmup or state mutation. All existing tracked blobs remain unchanged.

## Evidence and outcome

The existing closeout bridge verifies its independently pinned manifest, exact
universe/catalogue, ancestry archives, code identities, dispatches, events, raw
bytes and receipts. Qualification additionally binds each EPS row to its raw
locator, exact BASIC label, Decimal value, market mapping and original times.
Missing issuers and valid rows belonging to incomplete issuers remain present.
The 1978/1855/123/227 figures are reconciliation references, never output constants.

Eight exact dates map deterministically to calendar-quarter labels. This proves
calendar-window completeness, **not** independent fiscal-year/fiscal-quarter or
report-period semantics. The current source row schema has stock_id, date, type,
origin_name and value; it does not independently identify fiscal contexts.
Market is supplied by the hash-pinned catalogue, not invented from FinMind rows.
Accordingly fiscal_year/fiscal_quarter/report-period fields remain null.
Qualification returns NOT_QUALIFIED when that formal period proof is absent,
even if calendar-window checks pass. This does not revoke existing provider-only
candidate/features/Shadow use. No supplier reply is required as a new gate.

## Time and revisions

Prospective and historical qualification use separate requirements. Lack of PIT
evidence alone does not disqualify a period-qualified prospective provider.
The decision table permits PROSPECTIVE_QUALIFIED with historical UNPROVEN;
it is not an API accepting proof booleans instead of source validation.
This V1 has no validated fiscal/publication/revision bridge, so it cannot grant
qualification by caller-supplied assertions or extra unreviewed payload fields.

Neither retrieval/first observation nor provider date is publication time.
Original/latest, revision ordering and historical as-of selection are UNPROVEN.
Existing observations cannot be grandfathered into prospective formal use:
a separate approved activation and observations at/after it are necessary.
Even temporal eligibility never grants Production eligibility in this module.

## Calculation and next decision

Provider-defined quarterly EPS is not official common-share-basis EPS. Q4's
original/derived status remains unknown. No annual subtraction, sum or official
TTM is computed here. Any future model sums require their own calculation CR
and the name PROVIDER_DEFINED_UNADJUSTED_QUARTER_SUM.

Do not activate the provider yet. The smallest next action is a period-semantics
decision: independently substantiate the provider's fiscal/report-period
interpretation, or explicitly approve calendar-date-based provider period labels
as the formal model's different input contract. That is a substantive contract
decision, not something engineering can infer from dates or matching values.
No identical API re-scan is recommended without new evidence. Afterwards assess
a separate FORMAL_PROVIDER_ACTIVATION_CR, including incomplete-company behavior,
new post-activation observations and calculation compatibility. Historical use
still needs actual publication/revision evidence and remains UNPROVEN.

## Verification

Public CI is synthetic only. The real replay is local and separate. EPS values
retain Decimal representations, zeros and negatives; no values or unknown fields
are filled. All old contracts, production gates, restored historical materials,
ranking/strategy/weights and source identities are protected byte-for-byte.

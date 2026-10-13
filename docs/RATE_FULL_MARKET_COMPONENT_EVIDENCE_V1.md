# RATE Full-Market Component Evidence V1

Change request: `RATE-M-NONFUNDAMENTAL-FULL-MARKET-PRODUCTION-EVIDENCE-V1`.
Base: `f951186df3ffe6eeeedb19500a1cd4966433fc99`.
Scope: **19:30 EOD component evidence only**, not ranking, publication, warmup,
first refresh, scheduler activation, or intraday feed resolution.

## 30-record dependency decision

Do not replace `REQUIRED_DECISION_COVERAGE = 30` with 1978.

| Existing interface | Dependency | Decision |
| --- | --- | --- |
| Official source builder | `scripts/build_production_source_bundle_from_official.py`: authoritative 30-symbol contract, assemble/join checks and coverage output | Preserve |
| Legacy report / source validation | `scripts/publish_production_source_bundle_latest.py`: `REQUIRED_DECISION_RECORD_COUNT = 30`, source validation and delivery identity | Preserve |
| Development probe / rebaseline | `scripts/bootstrap_production_rebaseline_state.py`: exact `30/30` bootstrap evidence | Preserve; never use as full-market evidence |
| Scheduler | `tests/test_production_scheduler_change_control.py`: 30-record source and transformation proofs; new additive runtime remains opt-in | Preserve |
| Decision State / legacy acceptance | `src/production_live_state.py`, CER074-CER080 owners: explicit 30-record state coverage and historical pins | Preserve |
| Phase2 full-market interface | `scripts/build_phase2_production_source.py`, `src/full_market_materialization.py` and `src/full_market_rotation.py`: separate full-market path, but coupled Fundamental refresh/ranking/state behavior | Do not call from Phase M |
| Regression contracts | historical acquisition, publisher, rebaseline and cadence suites assert 30/30 | Preserve all tests and old formats |

Architecture: seven additive files. `RATE_FULL_MARKET_COMPONENT_EVIDENCE_V1`
is a separately named immutable artifact, never a legacy source bundle or Latest.
Every pre-existing main blob must remain byte-identical. No Production entry
point imports this opt-in builder.

## Source acceptance and offline replay

Input is a **separately accepted official normalization**, not manually supplied
rows. The caller supplies a trusted acceptance SHA independently of the input
manifest. Acceptance must bind the normalized history file SHA, complete raw /
receipt reference set, frozen normalization owners, exact universe, official
session evidence for each market, official TDCC period list, source snapshot,
and owner validation time. Each normalized row binds source ID and raw locator.
The reader verifies exact bytes, receipts, HTTPS authority, HTTP 200, no redirect,
market/family identity, timestamps and all source pins before calculation.
Acceptance must have scope `ACCEPTED_OFFICIAL_FULL_MARKET_EOD_HISTORY` and
`production_evidence_authoritative=true`. A development probe, rebaseline,
synthetic fixture or self-hashed JSON cannot acquire this status.

The source owner remains responsible for raw-to-normalized parser acceptance.
Phase M does not create or sign that acceptance, nor replace official parsers.
Real source replay is unavailable until those independently trusted materials
exist. Public CI tests the interface using explicitly synthetic acceptance and
cannot prove real Production source qualification.

Inputs contain all 1978 issuers, with four explicit history slots: stock,
benchmark, institutional and TDCC. Empty slots are missing, not silently absent
issuers. Unknown/extra/duplicate issuer identity is rejected. The exact accepted
universe SHA is fixed by contract; matching market counts alone is insufficient.

## Unchanged calculations and populations

The full 1978 universe is scanned before selecting any calculation subset.
Technical eligibility is independent of Fundamental and institutional eligibility.
The unchanged technical owner receives its naturally valid stock/benchmark
population; fewer than 20 cannot receive percentile scores. Current technical
history requires 180 aligned official sessions. Twelve technical replay sessions
support six-session Rotation deltas across seven Stage sessions.

Each of the seven as-of cross-sections uses original `compute_scores`,
`build_rotation_feature_histories`, `calculate_institutional_rotation`,
`calculate_m7`, `calculate_mhe` and `build_production_stage_evidence`. Institutional
history requires 26 aligned sessions, preserving the existing 20-session minimum
at the earliest Stage replay date. TDCC uses five actual officially listed periods
as of each replay session; no guessed weekly calendar or later period substitution.
Stage requires seven actual same-date feature outputs, a bound input snapshot,
and either accepted persistent prior Stage or separately authorized historical
reconstruction. Missing reconstruction authority blocks Stage only.

No formula, threshold, weight, Stage classification, percentile or tie rule changes.
Every source family and owner is LF-code-hash pinned to Base. Historical feature
replay is calculation lineage, **not Historical PIT qualification**.

Each verdict includes symbol, market, component, owner, status/reason, nullable
value, source observation, owner validation, raw/receipt source IDs, universe
identity, component population, source snapshot and calculation version. All
source references resolve through the immutable source binding. Stage preserves
its full original classified output, normalized score and field/state lineage.
M7 preserves PT/PV/MO/FI/IT/LH/RS; MHE preserves H5/H20/H60/H120.

`ranking_universe_count=1978` always. A component population is the automatically
derived calculable subset, not a manually selected list. Per-session technical
and institutional populations are retained as calculation lineage. Missing or
invalid issuers remain in the output with null, never zero. A missing source
inventory has `NOT_EVALUATED` for all issuers and no fabricated population ID.

Fundamental retains its already accepted 1750-member component population and
228 missing issuers. This is not a population mismatch. The readiness preview
reads its externally pinned owner verdicts without calling Fundamental again.
Top50/Long/Short requirements remain unchanged; Short does not require Fundamental.
Scores and ranks remain null and eligibility never grants authorization.

The older PR62 bridge's single technical-population parameter is not rewritten
or used to impersonate distinct component populations. This additive artifact
and preview expose separate scope bindings. Any subsequent authorized Ranking
consumer binding is a separate Control Center gate, not implicit activation here.

## Time and integrity

Official benchmark/session evidence must identify the latest legal EOD for both
markets. No trading date is inferred from weekdays or today's clock. Current
market/benchmark receipts are independently checked post-close and with the
existing 19:30 freshness validator (180 minutes); fresh TDCC cannot freshen an
old market receipt. Per-verdict observed time comes from its referenced receipts.
`observed_at <= validated_at <= evidence_as_of` is enforced. Cold read rechecks
The live CLI seals owner `validated_at` only after all calculation/validation
calls complete, then samples `evidence_as_of` and rechecks current freshness.
Explicit timestamps are reserved for deterministic evidence replay and synthetic
tests, not a pre-computation runtime completion claim. Cold read rechecks
freshness at the requested current review time, not only original generation.
Mixed acquisition times are retained, never called a simultaneous market snapshot.

Content identity binds core evidence, sources, populations, values and owners.
Output is external, create-only and immutable. Independent cold read replays
sources and unchanged owners. Network and writes outside new output are blocked
by the existing audit isolation guard. No state owner, publisher or ranking call.

## Acquisition boundary

Absent fresh accepted sources, the builder returns
`BLOCKED_ACQUISITION_AUTHORIZATION_REQUIRED` and
`PRODUCTION_EVIDENCE_ACQUISITION_REQUIRED`; it does not import the old 30-stock
payload or fabricate PASS. All 1978 source checks remain NOT_EVALUATED.

The attached acquisition proposal enumerates **four official session-discovery
requests only**, each once, sequential, >=13 seconds, timeout 30 seconds, zero
retry/fallback/redirect, public credentials only. It is not authorization or a
full history budget. Full history request counts remain unresolved until accepted
official session dates, TDCC available-period union and reusable raw inventory
are known. Then enumerate exact issuer/month, benchmark/month, market/session,
issuer/TDCC-period and any necessary official schema/form initialization requests.
Some legacy transports have built-in retry/fallback: they cannot be invoked
unchanged under this proposal. Bind a reviewed one-attempt transport before any
separately authorized acquisition. This PR supplies no network execution command.

## Verification and governance

Windows/Linux CI checks exact Base/Head, seven added files only, every inherited
main blob unchanged, all inherited regression groups plus new synthetic tests,
and the current-main replacement compatibility gate. No skips, relaxed assertions
or failure whitelist. Real local inventory and synthetic engineering results are
separate. Real raw/receipts/values never go to public GitHub or CI.

Always: `Ranking=NOT_AUTHORIZED`, `fallback_allowed=false`,
`Historical PIT=UNPROVEN`, original eight-quarter coverage credit 0,
`09:30/12:00 Intraday=BLOCKED_EXTERNAL`. No automatic merge, ranking,
publication, Portfolio/Ledger action or scheduler activation.

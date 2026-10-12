# RATE Phase J2-E - Fundamental-Only First Refresh Execution Wiring

This change is engineering wiring only. It does not authorize or execute the First Refresh and performs no financial requests or Production publication.

## Scope

The owner seals an immutable 1,984-request plan:

- 1,978 FinMind issuer requests in canonical symbol order.
- 6 MOPS revenue requests in fixed TWSE/TPEX x 2026-07/08/09 order.
- Single writer, sequential dispatch, at least 13 seconds between accepted capture boundaries.
- FinMind 20-second transport contract and MOPS 45-second timeout.
- Zero automatic retry, zero fallback, and no provider substitution.

Every accepted acquisition intent is bound through the existing acquire_once() dispatch evidence to the request-plan hash, ordinal, request key, authority, execution main SHA and publication destination. The accepted acquisition owner and its assertions are not modified.

A terminal failure or unknown outcome stops the plan. No automatic resume is allowed. Each success creates an append-only execution checkpoint that binds the plan, completed request set and trusted acquisition ledger head.

## Fundamental-only assembly

The assembler consumes only plan-bound First Refresh observations. It preserves all 1,978 issuers, valid partial evidence and missing periods. Missing values remain NOT_READY_MISSING_REQUIRED_PERIOD; zero-fill, imputation, prior-observation fill, legacy fill and silent issuer deletion are forbidden. Historical PIT remains UNPROVEN and the original eight-quarter coverage credit remains zero.

The module does not import Phase2, ranking, Top30/Top50, Stage, Rotation, M7/MHE, Portfolio, RPM or Decision State owners.

## Publication boundary

The formal destination is a separate Production Fundamental pointer:

artifacts/RATE_FUNDAMENTAL_FIRST_REFRESH_LATEST.json

This avoids mutating or reconstructing RATE_PRODUCTION_SOURCE_BUNDLE_LATEST.json and therefore leaves existing market, technical, ranking and state-related domains byte-identical. The Fundamental publisher reuses the accepted atomic primitives: content-addressed immutable staging, fsync, the shared OS writer lock, CAS against the previous Fundamental Latest identity, and exactly one same-directory atomic pointer replacement. Cold reconstruction verifies the committed snapshot.

A separate destination is intentional: Phase2 cannot be used as the First Refresh owner because it requires full EOD domains and binds ranking plus Decision State continuity.

## Authorization

The live-capable owner cannot run unless a later Control Center object has exact status FIRST_REFRESH_EXECUTION_AUTHORIZED and binds the main SHA, authority, universe identity, request-plan hash, maximum request count, destination identity, prior Fundamental Latest identity and single-use semantics.

J2-E itself keeps:

- First Refresh: NOT_AUTHORIZED
- Production publication: NOT_AUTHORIZED
- Ranking: NOT_AUTHORIZED
- Historical PIT: UNPROVEN
- Fallback: false
- Intraday: BLOCKED_EXTERNAL

CI is synthetic only. The full 1,984-entry plan, assembler, failure injections and atomic publication are exercised without financial endpoints.

## Latest-main compatibility revalidation

The compatibility base is `139505a3a6c33a19b7973c7f812497046a82d667`.
The historical engineering base remains `29f1781e3c460ccf9a816c5b9774b00374cedfe1`
in the original contract; it is not a future execution-main pin.
The runtime, CLI, contract and original 51 test assertions remain byte-identical
to reviewed Head `6d185cec4e29c4d69e63e5a1432e6d5d6e38c37b`.

Fresh exact-head verification inherits the current-main H-52 inventory, including
H-51, all earlier readiness, acquisition, publication, strategy and continuity
regressions. Both platforms also run the separate current-main replacement gate.
No existing main blob is changed. Inventory acceptance and provider readiness
do not grant First Refresh or ranking authorization.

After this PR is merged, a separate J2 Authorization Gate must generate and seal
the final request plan against the then-current main, authority and exact
universe. Compatibility review plans and synthetic authorization fixtures are
not formal execution authorization. This revalidation makes zero financial
requests, zero real First Refresh executions and zero Production publications.

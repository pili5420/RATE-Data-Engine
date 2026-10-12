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

## J2 authorization enforcement hardening

CR `RATE-J2-AUTHORIZATION-ENFORCEMENT-HARDENING-V1` repairs only authorization
consumption, seal/owner binding and pre-acquisition Latest drift detection. It
does not grant authorization or change acquisition, assembly, calculation,
ranking, scheduler, provider activation or atomic publication primitives.

The ordered runtime gates are: validate exact plan; current-main/clean-tree
guard; actual dedicated Fundamental Latest check; recompute seal and all five
owner hashes; validate authorization; atomic single-use claim; create execution
store; acquire; assemble; publish with the original final CAS.

`preexecution_seal()` includes the plan ID/hash, planned/maximum request counts,
main, authority, universe, prior Latest, destination and current owner hashes.
Its SHA256 covers compact sorted-key UTF-8 JSON with a trailing LF and excludes
the derived `seal_id` and `seal_sha256`. The seal ID is
`rate-first-refresh-preexecution-<seal_sha256>`. It always states
`first_refresh_authorized=false`.

Future Control Center authorization must bind that seal ID/hash and the entire
`owner_sha256` mapping. `authorization_id` is
`rate-first-refresh-authorization-<SHA256(canonical payload excluding
authorization_id and authorization_sha256)>`. `authorization_sha256` hashes
the canonical payload excluding only `authorization_sha256`, so it includes
the derived authorization ID. Changing any binding requires new Control Center
approval; these helpers do not issue authorization. A new authorized decision
can carry its own unique decision reference in the hashed payload.

The authorization additionally binds `authorization_consumption_root_identity`
to the normalized absolute authoritative artifacts root. Moving only the
execution root cannot bypass consumption, and moving the authoritative root
without new authorization is rejected.

Consumption records live at
`<authoritative artifacts root>/fundamental_first_refresh/authorization_consumption/<authorization_id>.json`,
not inside an execution root. The existing publisher OS lock serializes claims
and publishers. Lock contention waits at most ten seconds; this is not a
provider retry. Latest and seal bindings are rechecked under that lock before
the record is exclusively created, file-fsynced, directory-synced where
supported, and cold-verified. No record is overwritten. Exclusive record
creation is the irreversible claim point: a crash before request one still
consumes authorization, while a partial/corrupt record blocks reuse. Filesystem
administrators must preserve this immutable namespace; deletion is not a
supported recovery operation. No claim of tamper resistance against an
administrator deleting all evidence is made.

Records bind artifact kind, authorization ID/hash, root identity, seal ID/hash,
plan ID/hash, execution main, authority, universe, prior Latest, destination,
normalized execution root identity/path, consumed_at, CONSUMED status and a
canonical consumption hash. An existing intact record yields
`FIRST_REFRESH_AUTHORIZATION_ALREADY_CONSUMED`; corruption yields
`FIRST_REFRESH_AUTHORIZATION_CONSUMPTION_TAMPER`. Neither starts an execution.

Actual Latest drift yields `FIRST_REFRESH_PREACQUISITION_LATEST_DRIFT` before
claim, execution-store creation or capture. Drift arising while waiting for the
lock is rechecked. Changes after claim remain protected by the unchanged final
publication CAS. Existing success checkpoints, unknown-outcome STOP and separate
Control Center continuation requirements remain unchanged.

Verification binds Base `e38f3f4b7a588a607985a1b6fde5289568175d41` and the new PR
head, permits only the six explicit hardening files, preserves every other main
blob, and compares the AST of all original 51 test methods/assertions and the
unchanged plan/dispatch/assembler/publisher/checkpoint owners. Current-main
inherited tests, original 51 tests and new hardening tests are counted separately.
Windows/Linux CI and the current-main replacement gate use synthetic materials
only. Positive-status synthetic authorization uses an authority that cannot
match the real activation seal; it is not a live grant.

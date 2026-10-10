# Fundamental Eligibility Subgate V1

CR: `RATE-FUNDAMENTAL-ELIGIBILITY-SUBGATE-V1`. Approved policy direction;
engineering only. No provider, warmup, ranking runtime or publication activation.

## Boundaries

The exact catalogue retains all 1978 issuers (TWSE 1085, TPEX 893). The CLI
reuses the existing historical catalogue verifier, with externally supplied file
hash and source commit. Counts alone are not an identity. The engine receives
owner **verdicts**, not replacement raw financial data; it does not implement
another provider adapter, period mapper, source parser or score calculator.

The JSON contract defines the input evidence-state schema and all independent
readiness fields. Each verdict binds its owner, exact mandatory periods (where
applicable), status/reason, observations/validation, source references and
component population. PASS is an existing owner's complete validation result,
not merely an observation count or a caller's assertion that a value exists.
The trusted bundle digest must come from the verified owner delivery, outside
the bundle. CLI reference replay checks byte integrity, not source semantics;
it cannot turn unqualified data into a qualified source. No writer for these
owner verdicts is installed in any Production workflow in this change.

EPS and revenue readiness describe their respective input evidence. Fundamental
input readiness additionally requires formal EPS period identity, not its own
calculated output. Ranking separately requires the existing Fundamental owner's
finite output. A calendar-contract PASS does **not** satisfy formal EPS
qualification. A null or UNDEFINED_ZERO_BASE revenue period is not PASS. Missing
required periods use MISSING_REQUIRED_PERIOD, preserving each missing reason.
Unknown technical inputs remain NOT_EVALUATED, not inferred from EPS coverage.

## Ranking Gates

Top50 and Long require all their own components, tie inputs and Fundamental
requirements. Otherwise score/rank are null. Short does not depend on Fundamental
but still requires M7, Rotation, SmartMoney, MHE, Stage, RelativeStrength and
Liquidity. Long does not gain a new Rotation dependency. Stage, Rotation, M7
and MHE readiness reflect their respective owner's required inputs only. A
validated input verdict may have a null component value before calculation:
input readiness remains true, but a dependent ranking reports NOT_COMPUTED and
stays ineligible until that owner supplies its finite component value.

The gate returns INPUT_READY_NOT_CALCULATED until an existing ranking owner
supplies a verified result bound to symbol, market, population, input-row digest
and ranking kind. `gate_owner_ranking` is only a mask: it either preserves that
result exactly or returns null. The caller remains responsible for validating
the existing owner's calculation; a binding hash alone is not such validation.
It never computes scores, changes weights,
renormalizes factors, supplies zero, sorts ranks or changes tie rules. An eligible
engineering result is still not a trade or Production authorization.

All component population references bind the pinned market universe. Do not
pre-filter technical percentile populations by EPS readiness. A future formal
integration must independently authorize and verify factor-specific population
semantics; this gate does not invent Fundamental values for missing issuers.

## Continuity

Outputs use a separate eligibility-overlay identity, not a Decision State alias.
The previous overlay content hash and snapshot id bind incremental history.
Issuer history and the entire passed continuity context, including Roy, AI Paper
and Transaction Ledger, are copied unchanged. Holdings are inspected only to
annotate RANKING_INELIGIBLE_HELD_POSITION. No BUY, SELL, forced exit, reset or fill
is emitted. An account-owner transition requires its own authorization rather
than being hidden inside an eligibility update. Existing overlay bytes must
remain immutable; each CLI invocation requires a new output directory.

## Offline Opt-In

`scripts/build_fundamental_eligibility.py` requires input/context file hashes,
the original universe evidence path/hash/commit, and a new output directory.
An incremental invocation additionally requires the previous overlay and its
trusted file hash. The CLI validates reference bytes, exact issuer membership,
period verdicts, owner identities, populations, availability and previous overlay
before writing. It never fetches market/financial data or updates a formal state.

The pure engine takes canonical content pins; the CLI first checks externally
provided **file** pins. Merely computing a digest from untrusted input is not
source validation. Public tests use explicitly synthetic owner verdicts; their
PASS does not grant real provider qualification or live credit.

## Deferred Change Control

Formal provider activation, calculation semantics, Warmup Policy acceptance,
formal ranking-consumer integration and Production publication remain separate
CRs. `FUNDAMENTAL_EPS_PERIOD_IDENTITY_UNPROVEN` is unchanged. Full-market accounted
counts never imply full warmup PASS. Historical PIT remains UNPROVEN, fallback
false, authorized intraday feed BLOCKED_EXTERNAL, full Production NOT_ALLOWED.
Report Soak/CER081 and four-cadence PARTIAL_VALID semantics are untouched.

# Public Official Partial-Valid Runtime V1

Change request: `RATE-0930-1200-PUBLIC-OFFICIAL-PARTIAL-VALID-V1`.
Fixed engineering base: `af5ed52a78a7cea761e985011d234aa66f18b3e1`.

## Boundary

The explicit `--public-official-partial` mode is limited to 09:30/12:00.
The existing documented registry supplies public daily market, TWSE benchmark,
issuer metadata and monthly revenue evidence. Seven required dataset views use
six distinct registry endpoints (TPEx daily/metadata share one exact response).
This is a new report-only artifact, NOT a complete formal decision source bundle.
The original full-source validator continues to reject it. No history loader,
Fundamental calculation, price-dependent strategy or trade execution is invoked.

The state contains independently named gates:

| Field | Public evidence succeeds; authorized intraday feed unavailable |
| --- | --- |
| public_official_evidence_gate | PASS |
| market_intraday_price_gate | BLOCKED_EXTERNAL |
| report_runtime_status | PARTIAL_VALID |
| full_intraday_decision_status | BLOCKED_EXTERNAL |
| full_production_acceptance | NOT_ALLOWED |
| fallback_allowed | false |

`validation_status=PASS` on transport/persist evidence means its declared partial
contract is valid, NOT FULL_PRODUCTION_PASS. Full acceptance and soak credit
remain disallowed. External dependency status and its no-fallback requirement
are unchanged. Unconfigured announcements, attention/disposition/suspension and
TPEx benchmark are explicitly NOT_CONFIGURED_NOT_ASSERTED_CLEAR. Issuer metadata
is never converted into a claim that an issuer is trading normally.

## Evidence And Time

Raw responses are immutable exact bytes with receipt hashes, explicit row
locators, registry endpoints/parser identities, observed/validated timestamps.
Only allowlisted documented endpoints are selected; changed final URLs fail.
Daily/benchmark evidence must match the existing previous legal trading day.
Observation freshness is 30 minutes; public publication ages are explicitly
bounded in the new contract. No missing date is defaulted to today's date.
Source/schema/identity/duplicate/stale/future/hash failures stay FAIL_CLOSED.
The existing exchange-calendar limitations are not relaxed by this mode.

The 12:00 fetch is independent of 09:30. Parsed source-row hashes determine
NONE/DETECTED; receipt/observation changes alone do not manufacture a data delta.
Evidence state, symbol-linked watchlist references and commentary inputs update.
No unconfigured risk source is silently marked clear.

## Persistence And Continuity

Use the actual canonical persisted 07:30 predecessor, then the actual canonical
09:30 predecessor. No reconstruction of an accepted historical synthetic state
and no bootstrap/reset is permitted. Existing account, transaction history,
rank outputs and model state are preserved by deep equality at both runtime and
publication boundaries. Current price/volume are null with explicit blocked
module statuses. Previous records remain separately labeled historical records.
Signals/intents are preserved, not recalculated or executed.

Scheduler ordering: resolve previous state -> public acquisition/validation ->
partial runtime -> archive report-consumption raw/receipts -> replay archived
sources -> publish immutable state/ready manifest. The report publisher does not
update formal SOURCE_BUNDLE_LATEST. Source bytes travel in the canonical state
tree and uploaded artifacts, independent of acquisition runner paths.
The shared existing scheduler concurrency group remains intact.

The persisted 12:00 state is accepted by the unchanged 19:30 context resolver.
This does not certify completion of the legacy 19:30 acceptance runner, which
still has historical fixed-state bindings; 07:30/19:30 specifications are not
changed here.

## Engineering Acceptance

Public CI uses synthetic responses only; no official market/financial request is
made during engineering verification. The verifier executes every selected old
regression unchanged on BOTH the fixed base and head, in isolated copies, and
separately runs new tests. It preserves failures and tracebacks, checks byte/blob
isolation, and exports a synthetic persisted-chain proof.

Known fixed-base failures: ten historical CER076-079 reconstruction errors
(`RECONSTRUCTED_0730_STATE_MISMATCH`) and two CER081 scheduler-coverage failures.
No tests, assertions, accepted hashes or legacy scheduler rules are rewritten
to make this PR green. No-new-regression equivalence is NOT all-regressions-pass.
The strict CI acceptance remains nonzero until all selected regressions pass.
Control Center review must address these baseline limitations before claiming
the original all-PASS acceptance, including full 19:30 acceptance.

No live production state was published by the engineering run. This PR does not
enable a new schedule; it changes only the two existing intraday schedule paths.
No ranking, strategy, model weight, source authorization or Shadow/Forward
definition is modified.

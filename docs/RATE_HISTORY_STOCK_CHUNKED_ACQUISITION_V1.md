# Stock-History Chunked Fail-Closed Acquisition

CR: `RATE-MH-CHUNKED-FAIL-CLOSED-ACQUISITION-001`.

This additive layer changes orchestration and evidence isolation only. Existing
source, transport, parser, normalization, authorization claim and readiness owners
are unchanged. It does not qualify an empty period or a TPEx physical unit.

## External Scope Approval

`stock_scope()` creates an **unapproved** proposal. Its exact entries contain only
market, symbol and period. `build_manifest()` additionally requires an independently
trusted Control Center scope-approval SHA, not a status flag or a self-derived pin.
The approval binds the canonical scope identity, main, universe, market, material
scope and external scope-evidence SHA. There is no production scope approval writer.
Synthetic tests construct clearly marked engineering approvals in temporary roots.

The exact 1978 universe remains in every ordinary history Plan. A scope can request
fewer issuers without deleting anyone from that universe. The remaining 33 real
start/product cases are not resolved here. Existing planning drafts are not accepted
production scopes and are not embedded as request budgets.

## Deterministic Partition

One manifest covers exactly one market. Symbols sort ascending; periods sort
descending using the existing Plan owner. Consecutive whole issuers are greedily
packed subject to **both** 10-issuer and 100-request limits. Request endpoints,
methods, parameters and keys come exclusively from `request_entry()`/`build_plan()`.
No liquidity, ranking, row count, timing or failure-history repartition is allowed.
The manifest has no clock-dependent fields; identical approved scope and main
produce identical canonical bytes. Every scope entry occurs exactly once.

## Independent Execution

`materials()` derives one ordinary Plan, Seal and pending Candidate in a unique
chunk namespace. The original executor owns the formal authorization validation,
single-use consumption, request pacing, evidence capture and first-error STOP.
Real TPEx material generation is Plan-only while the frozen unit HOLD applies: no
executable Seal or Candidate is returned. Synthetic TPEx proves the same partition
without removing the real gate.

`execute_chunk()` invokes exactly one chunk, never a loop over chunks. Its campaign
coordination lock is separate from each scanner's evidence/consumption locks. After
a STOP or an error following claim, append-only `HALTED.json` blocks later chunk
execution on restart before any further claim. Prior successful chunk evidence is
not changed. Before claim, the wrapper also checks original chunk consumptions,
STOP/results and replays previous successes, covering a crash before the outer
halt file was written and rejecting prior-evidence mutation. A successful return
also does not start another chunk automatically.
Every separate explicit invocation must present a distinct formally trusted
authorization. This engineering CR creates and claims no real authorization.

The first failing request stops the active chunk; subsequent ordinals do not run.
An ambiguous empty payload remains `HISTORY_EMPTY_PERIOD_UNQUALIFIED`, not a valid
empty, zero value, inferred suspension, skip or pre-listing conclusion. Network
failure and unknown outcome likewise stop; consumed authorization cannot resume.

## Offline Aggregate

`aggregate()` requires the approved manifest, a separately pinned accepted
Benchmark180 execution binding, and separately pinned chunk execution bindings.
Each original root is cold-replayed through `history_acquisition_execution.replay()`.
Plan, Seal, authorization, consumption, source hashes, sessions, STOP and checkpoints
are validated by that existing owner. Source observations and ancestor benchmark
Producer main remain original; no acquisition event is copied into a new ledger.

The accepted benchmark can retain an ancestor main pin when existing replay owners
and source-native cutoffs are unchanged. Stock plans must match the manifest main,
universe, market, cutoff and exact entries. Duplicate/unmanifested chunks, repeated
execution/consumption/authorization identities or stock request keys fail closed.

- `COMPLETE`: all manifest scope entries have successful original validation events.
- `PARTIAL_HALTED`: a supplied chunk stopped or a required chunk is not completed;
  all already-validated events remain visible to the existing coverage owner.
- `INVALID`: conflict/tamper; no trusted coverage is returned.

`COMPLETE` is **scope acquisition completion**, not full-universe readiness,
calendar180, Phase M decision eligibility, Ranking or Production acceptance.
Only the aggregator calls the existing `coverage_inventory()` on original accepted
benchmark plus stock events for combined inventory; it does not rewrite formulas.
TPEx issuer readiness remains blocked by existing unit semantics. A single-market
manifest cannot silently grant another market's stock coverage.

## Future Replacement Governance

No replacement/resume implementation is included. A failed or unattempted scope
requires Control Center defect review, fresh exact scope, manifest revision or
replacement artifact, fresh Plan, Seal and authorization. Unknown outcomes cannot
be resent and confirmed successes cannot be relabeled as new acquisitions. Existing
successful roots remain useful through original hash references in aggregation.

Historical PIT remains `UNPROVEN`; `calendar_180_ready=false`; Intraday remains
`BLOCKED_EXTERNAL`; TPEx unit remains `BLOCKED_EXTERNAL_DOCUMENTATION`; Ranking is
`NOT_AUTHORIZED`; production eligibility and fallback remain false. The strict
Phase M common-latest and final12 alignment gates are untouched.

## Verification

The new verifier runs inherited synthetic groups and new chunk tests from exact-head
exported source. A separate existing current-main replacement/continuity verifier
runs unchanged. Every pre-existing base blob is protected byte-for-byte. Public CI
uses synthetic fixtures only on Windows and Linux, with zero skips, relaxed
assertions or failure whitelists. There is no live CLI workflow, scheduler or
automatic production manifest generation in this CR.

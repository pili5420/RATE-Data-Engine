# RATE Thin Work Consumer Phase A

`RATE-THIN-WORK-CONSUMER-PHASE-A-V1` is a deterministic shadow-acceptance
consumer harness. It validates a RATE Thin Work production bundle manifest and
a persisted previous RATE state, then emits machine-readable preview evidence.

The harness is read-only. It never ingests market data, recalculates RATE
strategy outputs, falls back to alternate data, writes Production LATEST,
advances persistent state, or mutates portfolio or transaction ledgers.

Required gates:

- contract version, production snapshot, run, and commit binding
- explicit expected run, commit, production snapshot, previous-state ID, and
  previous-state hash binding
- freshness, validation, source status, required datasets, blocked dependencies
- canonical previous-state hash, lineage, portfolio/account reference, and
  transaction-ledger continuity

After all gates pass, the harness only allows incremental evidence, decision
input, portfolio input, and ledger input previews. All mutation authority fields
remain false.

The CLI requires all expected identity arguments. Omitting any expected binding
fails closed instead of accepting the manifest or state values as self-authored
truth.

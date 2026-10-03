# RATE Thin Work Consumer Phase A

`RATE-THIN-WORK-CONSUMER-PHASE-A-V1` is a deterministic shadow-acceptance
consumer harness. It validates a RATE Thin Work production bundle manifest and
a persisted previous RATE state, then emits machine-readable preview evidence.

The harness is read-only. It never ingests market data, recalculates RATE
strategy outputs, falls back to alternate data, writes Production LATEST,
advances persistent state, or mutates portfolio or transaction ledgers.

Required gates:

- contract version, production snapshot, run, and commit binding
- freshness, validation, source status, required datasets, blocked dependencies
- previous-state requirement and previous-state continuity

After all gates pass, the harness only allows incremental evidence, decision
input, portfolio input, and ledger input previews. All mutation authority fields
remain false.

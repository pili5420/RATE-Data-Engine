# TPEx Discovery Benchmark Close Compatibility

Defect: `RATE-MD-DISCOVERY-TPEX-BENCHMARK-SCHEMA-001`.
Base: `4cc943695ebad2cb6f94dacb60e94312d04e2547`.

## Root Cause And Repair

The second authorized discovery attempt stopped at ordinal3 after HTTP200 from
the unchanged TPEx benchmark endpoint. Its eight records have exactly
Date/Open/High/Low/Close/Change. The formal owner
`src/benchmark_history.py::normalize_benchmark` already accepts capitalized
Close in its raw_close pick. Discovery omitted that exact alias.

The runtime change is **one alias addition** to the TPEx benchmark branch of
response_session. Existing ClosingIndex/Chinese aliases/lowercase close remain
unchanged. No fuzzy matching, endpoint change, parser family, new source contract,
price synthesis, strategy change or new provider is introduced.

Discovery remains a session/date/schema bridge, not an alternative price
normalizer or price-admission gate. The unchanged formal benchmark owner performs
the numeric normalization. This fix does not redesign existing numeric, alias
conflict, market-daily or session semantics.

## Evidence

Public tests use eight synthetic records with the captured six-key schema, not
actual financial values or copied HTTP bytes. They show all rows normalize with
the unchanged owner and validate through discovery with every locator retained.
Unsupported aliases, malformed structures/JSON, duplicate JSON keys, nonfinite
JSON, invalid/future/pre-close dates still reject. TWSE and TPEx market-daily
regressions are preserved. Mock runtime proves valid ordinal3 completion and
unsupported ordinal3 stop without a fourth dispatch.

Separate local same-bytes replay verifies the real immutable failed raw, receipt
and intent: old discovery fails while the corrected discovery accepts all8;
the existing benchmark owner accepts all8 in both versions. Existing completed
TWSE events replay identically. Real values/raw/receipts stay local and are never
uploaded to public repository or CI.

The old stopped ledger, two checkpoints, three actual requests and consumption
record remain unchanged. Old-main read-only preflight rejects the CONSUMED
authorization. Do not reuse it, resume the old root or relabel its STOP as PASS.
Offline parser success is not a new discovery execution or request authorization.

## Isolation And Acceptance

Five-file scope: one-line executor repair, new synthetic tests/doc/verifier and
minimal exact-head workflow retargeting. The historical verifiers and all old
tests stay byte-identical. The new verifier enforces the exact single tuple edit,
preserves every other main blob and runs1553 inherited plus24 new tests on
Windows/Linux. The unchanged current-main replacement/continuity gate also runs.
No skip, relaxed assertion or failure whitelist is allowed.

Retry0, fallbackfalse, redirectfalse, timeout30, interval>=13, single_usetrue,
auto_resumefalse and fail-closed semantics are unchanged. No ranking, M7, MHE,
Stage, Rotation, Smart Money, Top50/Top30, intraday or Historical PIT policy
changes. No Production/state/Portfolio/Ledger/scheduler mutation.

Official/external data requests0; discovery requests0; financial requests0.
GitHub engineering push/PR/CI connections are separate from this zero-data-network
validation. Stop at READY_FOR_CONTROL_CENTER_REVIEW with PR OPEN / UNMERGED.
Any later live attempt needs separately approved fresh main-bound authorization;
this engineering PR creates none.

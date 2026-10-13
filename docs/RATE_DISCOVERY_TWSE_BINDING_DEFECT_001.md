# Discovery TWSE Owner Binding Repair

Defect: `RATE-MD-DISCOVERY-TWSE-ENDPOINT-BINDING-001`.
Base: `b0853df9d435f4c5842b1716a32fdb52f6f5a1f8`.

The original discovery plan selected the RWD afterTrading family while the
accepted TWSE owner and registry select OpenAPI exchangeReport. A saved HTTP200
response was OK/MS general-market statistics, not the assumed index table.
The request stopped at ordinal1 with no completed checkpoints. That is immutable
defect evidence, not a successful acquisition or permission to resend.

## Repair

TWSE routes now derive directly from `src.sources.twse.BASE` plus the same
exchangeReport paths used by `TWSEAdapter.fetch_benchmark/fetch_daily`.
TPEx continues using `BENCHMARK_ENDPOINT/CURRENT_DAILY_ENDPOINT`. All four
owner comparisons must match. No discovery target can retain the old RWD paths.

The candidate reader accepts the existing OpenAPI record-array contract, not
RWD dictionaries/tables. Exact Date/Chinese-date aliases must agree and all
records must identify one session. Benchmark field/numeric rules reuse
`public_official_partial_valid._first/_numeric`; stock fields match the frozen
TWSE daily owner. Missing official closes remain missing. No values are created,
prices selected, rows dropped, or formal source parser semantics modified.

## Schema Evidence And Limits

The unchanged source owner, official registry, public-official validator and
its inherited tests define the accepted OpenAPI contract. Local historical
owner landing material additionally preserves benchmark record arrays with
Chinese date/index/close fields and stock arrays with Date/Code/ClosingPrice.
The files and provenance manifest are pinned against prior immutable evidence.
Pure offline replay checks every record and raw-row locator, not just a sample.

The old landing writer serialized `raw_payload` JSON. Those files are **saved
parsed JSON**, not the exact HTTP response bytes: their file SHA differs from
the original transport content_hash. Do not relabel them as wire-byte receipts,
current-market qualification, a fresh acquisition, or Production acceptance.
They provide captured schema evidence consistent with existing owner contracts.
No true values/raw/receipts are uploaded to CI. CI uses explicit synthetic
fixtures and a redacted structural model of the captured MS failure. Local
same-bytes replay of the real failed response remains separately recorded.

If future official bytes do not satisfy this frozen known contract, execution
must stop and require `REAL_TWSE_OPENAPI_SCHEMA_QUALIFICATION_REQUIRED`; no new
aliases or endpoint changes may be guessed in a live root. Any qualification
request requires separate Control Center authorization, never automatic fetching.

## Consumed Authorization

The original authorization remains CONSUMED / NOT_REUSABLE. The old root,
consumption file, intent, raw/receipt, STOP, result and timestamps are unchanged.
The old-main reader cold-replays its failure and read-only preflight rejects
reuse. The new plan rejects the old endpoint binding even with a recomputed
old-plan digest. The new parser/head must not be written into old evidence.

After review and merge, any next live gate requires a fresh main-bound plan,
fresh seal, fresh roots and a new Control Center authorization. This PR creates
no operational authorization, claims nothing and performs no live discovery.

## Verification Scope

Seven reviewed files only: executor, existing discovery fixtures/expected owner
routes, current workflow, documentation, dedicated binding-fix verifier/tests.
All other main blobs remain identical, including source owners, Phase M,
Fundamental, ranking, transport, acquisition/claim logic, original verifier and
the runtime contract. Original82 discovery tests retain their assertions except
the explicitly defective endpoint expectation and table-format fixtures.

The new verifier runs all1529 inherited tests plus new repair regressions on
Windows/Linux and keeps the unchanged replacement/continuity gate. It checks
the exact repair allowlist and all unmodified main blobs; it does not apply PR64's
historical eight-additive-file allowlist to this separate repair PR.

Retry0, fallbackfalse, redirectfalse, timeout30, interval13, single-usetrue,
auto-resumefalse remain unchanged. No real official/financial requests, ranking,
publication, State/Portfolio/Ledger/scheduler writes or Historical PIT promotion.

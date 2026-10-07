# Fixed-Universe Provider EPS Coverage

Scope: PROVIDER_COVERAGE_VALIDATION_ONLY, READY_FOR_REVIEW, no active consumer.
The candidate adapter now parameterizes symbols/window for receipt replay and
uses one EPS extraction/record-construction implementation. Its original strict
three-company builder/schema and 21 regression tests remain intact.

## Universe And Plan

`load_universe` reads a supplied hash-pinned, previously approved historical plan
as evidence only. It verifies its file hash, original execution commit/authority,
internal plan/catalogue hashes, existing catalogue eligibility rules, exact
market mapping and shard-symbol reconciliation. Production defaults require
TWSE 1085 + TPEX 893 = 1978; never substitute FinMind's current stock list.

The separate coverage plan identity binds the complete symbol/market list,
catalogue source path/hash/commit/as-of, code base/head, pinned delivered transport,
FinMind policy and 2024Q3 through 2026Q2 window. This is not a warmup plan/resume.
Changing any binding cannot reuse this plan's ledger or counters.

## Local Scan

`scripts/scan_provider_eps_coverage.py` accepts explicit input/transport/evidence
paths and hashes plus reviewed code SHAs. Output must be external and new, unless
`--continue-ledger` is explicitly supplied for the identical coverage plan.
All original three-company 24 rows are reverified/reused without new requests.
Receipts and raw remain local; no public results containing real values are made.

The script imports the unchanged hash-pinned delivered transport's `capture`
function, not its bulk collector/main. It uses only per-symbol requests:
TaiwanStockFinancialStatements, 2024-07-01 through 2026-06-30. No PDFs/MOPS/revenue
requests, full-market subscriber endpoint, account signup or payment is performed.
An existing FINMIND_TOKEN is read only in memory, never logged or written.

Default batch bounds: at most 280 new requests, 3600 seconds, at least 13 seconds
between request starts, sequentially, zero retries. Documentation says anonymous
300/hour and authenticated free members 600/hour; a token does not establish a
paid tier. Anonymous remaining quota is not observable via authenticated user_info.
The first needed data request establishes actual access; do not make a redundant
stock probe. HTTP/service 401/402/403/408/429/5xx or network failure stops later
same-host requests. Persisted shared blocks do not disappear on continuation.

References: https://finmind.github.io/quickstart/ and
https://finmind.github.io/api_usage_count/ (402 is also a quota response).

## Append-Only Ledger And Counts

Immutable `plan.json`, per-company `intents/` before requests, and sealed `events/`
provide crash recovery without duplicate requests/counts. A saved receipt can
finish an interrupted intent offline; an intent lacking a receipt is UNKNOWN,
never silently retried. Existing completed/failed companies are not refetched.
Only a bounded-batch stop can continue automatically under the same conditions.
Events are replayed against referenced bytes/receipts before reports are trusted.

Three counts are separate:

- accounted_for / 1978: companies with a completed reused/request result; pending
  and unknown request outcomes are excluded. All 1978 identities are nevertheless
  listed in the inventory; that is not acquisition completion.
- eps_complete_companies / 1978: exactly eight valid fixed-window positions.
- valid_company_quarters / 15824: individually verified unique positions.

Company statuses: COMPLETE, NO_EPS, HISTORICAL_INSUFFICIENT, ACCESS_FAILED,
VALIDATION_FAILED; reports add NOT_ATTEMPTED and REQUEST_OUTCOME_UNKNOWN.
Missing, duplicate, conflicting, nonfinite and identity/hash failures are distinct.
Duplicate/conflicting keys retain raw/issue evidence and invalidate that position;
valid other quarters survive. Transport/identity/hash errors invalidate only that
company response, not other stocks. Extra periods remain in raw and are excluded.
Zero/negative EPS and exact decimal strings are preserved, never filled/replaced.

Q4/filing/revision/public time remain unknown. Provider dates are local calendar
quarter mappings, not proven filing or announcement dates. Each old/new observation
stays attached to its own receipt. Full-universe availability time is null until
all companies have eight positions; then it cannot precede the latest acquisition.
This is not a simultaneous market snapshot or 2026-10-05 Historical PIT acceptance.

## Revenue And Verification

The read-only revenue inventory reuses existing MOPS byte/receipt and revenue-row
validators for the latest three periods actually present in the bound saved plan
receipts. It lists source hashes/times, valid company-period coverage and missing
positions, without fresh requests or changing formulas/source. Those saved periods
are not a new announcement anchor. EPS-only coverage is not complete Fundamental.

New CI uses explicitly synthetic stock/response fixtures and original candidate
regressions only. It never invokes the scan CLI or supplied local real materials.
The shared isolation checker permits only this delivery's candidate/helper changes
and six additions, and fingerprints every other existing tracked file. Existing
Production entries cannot acquire candidate/coverage imports. Original PR #29-#32
commits/evidence/test files are not overwritten or frozen acceptance replayed.

Local results include per-company ledger, 1978-company/15824-position matrix,
read-only revenue inventory, source/code invariance and actual execution bounds.
Production=false; original formal coverage credit=0; formal acceptance=NOT_PERFORMED.
Contract/artifact translation, full required EPS/revenue inputs, Historical PIT,
formal scoring/ranking and deployment remain separately unauthorized. No merge,
Work/B1 activation, Production/LATEST/state/Portfolio/Ledger writes, Run-5 or rebaseline.

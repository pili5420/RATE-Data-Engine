# Official Session Discovery Execution V1

CR: `RATE-MD-OFFICIAL-SESSION-DISCOVERY-EXECUTION-WIRING-V1`.
Base: `6a2108c6ce326bf90806ab0cdd7ab84e7131a643`.
This is additive engineering, not discovery authorization or a historical calendar.
No live HTTP requests are made during engineering or CI. No scheduling is enabled.

## Exact Scope

1. TWSE benchmark: `src/sources/twse.py::BASE + "/exchangeReport/MI_INDEX"`
2. TWSE market: `src/sources/twse.py::BASE + "/exchangeReport/STOCK_DAY_ALL"`
3. TPEx benchmark: current-main `src/sources/tpex.py::BENCHMARK_ENDPOINT`
4. TPEx market: current-main `src/sources/tpex.py::CURRENT_DAILY_ENDPOINT`

All are GET, timeout 30 seconds, one attempt, ordered, minimum 13 seconds between
capture boundaries. No redirect, retry, fallback, alternate host, provider
substitution, credentials or automatic resume. Environment proxies are not read
by the dedicated transport; default HTTPS certificate verification is unchanged.
No existing retry/fallback source transport is called. Source owners are frozen.

## Binding And Operations

`build_plan(main_sha)` emits deterministic native-JSON content identities.
Its four entries and types must exactly equal the generator, not merely have a
matching self-reported digest. The universe is the accepted exact identity
`18ff7df30b80df8082efd94f71c894b23da5cc87f945a5fd889d5d92dfc3d43e`.

`--operation plan` has no network or consumption side effects and emits a plan,
seal and **unsigned pending candidate** to a new external directory. The seal
binds executor/transport Git-normalized LF bytes, main SHA, universe, plan, roots,
NONE previous discovery latest, budget four and single use. No old Phase M
request plan or contract is changed by this new opt-in mode.

`--operation preflight` cold-loads the bindings, checks exact clean main equals
origin/main and the plan, checks both owners are committed in that main, verifies
roots/seal and validates the pending candidate. This is not authorization.

`--operation execute` requires a Control Center-issued object with the exact
schema and `SESSION_DISCOVERY_EXECUTION_AUTHORIZED` status. No authorization
issuer is implemented. Content digests bind material integrity, not a digital
signature or an independent proof of human approval. Supplying a fabricated
authorized JSON is not an authorized operational action. Until review, merge,
a fresh merged-main plan/seal and Control Center discovery authorization, live
execution is not allowed. The engineering branch itself fails the main guard.

Future invocation shape (not a usable authorization):

```powershell
python -B scripts/run_session_discovery_execution.py --operation execute `
  --main-sha <approved-merged-main> --plan <approved-plan> --seal <approved-seal> `
  --authorization <control-center-authorized-object> `
  --artifacts-root <discovery-owned-external-root> `
  --consumption-root <sealed-shared-external-claims-root> `
  --output-dir <new-child-of-discovery-root>
```

The roots are sealed absolute path identities; changing output children cannot
reuse an authorization. Changing either sealed root invalidates authorization.
Roots cannot be any Git checkout/worktree, each other, nested in one another, symlinks or
junctions, or known Production/state/portfolio/ledger/scheduler namespaces.
Use newly dedicated discovery roots; do not designate a sealed ancestor archive.

## Irreversible Claim And Evidence

Validation precedes any write/claim/dispatch. A discovery-only OS writer lock
guards the sealed consumption root. Create-only fsync consumption is the single
irreversible claim point and is also atomic under competing claim processes.
Partial consumption records remain occupied after a crash; they are never
repaired, removed or reused. The same authorization cannot run again in another
process or output child, even when the first request fails. No Production pointer
is written. Discovery latest is an absence precondition, not a publication target.

Each boundary rechecks main/owners, persists a content-bound intent, then checks
outbound monotonic timing before its single transport call. Existing DispatchGate
is reused without changing its writer semantics. Metadata uses native int/float
JSON with duplicate/nonfinite rejection, not the financial Decimal reader.
The 13-second lower bound uses anchor-to-dispatch, not only sleep duration.
Early-returning sleeps loop until enough time elapsed. Each execution is one
process session; no cross-clock-domain subtraction or automatic continuation.
Measurement is `CAPTURE_CALL_NOT_HTTP_WIRE_START`.

Responses retain exact content-addressed raw bytes and canonical immutable
receipts, then undergo source/schema/date validation. Receipts preserve failure
HTTP responses as well. Completed events hash-chain to their predecessor and
each completed ordinal has an immutable checkpoint. Checkpoints are evidence,
not a resume mechanism. Independent cold replay verifies original raw/receipt,
intent/digest/session, event chain, checkpoints, consumption and final result.

HTTP, timeout, redirect, schema/identity/date/hash errors, unknown outcome,
worktree/main/owner drift or tool errors stop all remaining requests. STOP and
traceback are create-only; claim remains consumed. No fifth request is possible.

## Session Semantics

TWSE accepts the formal OpenAPI record-array family, not RWD table JSON.
Exact `Date`/`日期` fields must resolve to one unambiguous session. Benchmark
identity/close fields reuse the accepted public-official owner contract; market
records use the existing daily owner's `Code`/`ClosingPrice` fields. All index
rows and raw locators are retained; this is date discovery, not index-price
selection. See `RATE_DISCOVERY_TWSE_BINDING_DEFECT_001.md` for compatibility evidence.
TPEx accepts its list-of-records products with explicit Date and product-specific
fields. ROC/Gregorian dates are normalized only under exact supported formats.
Nonfinite/duplicate JSON keys, ambiguous mixed daily dates, future sessions and
same-day pre-close sessions are rejected. Missing individual stock close values
are not filled or interpreted as unavailable calendar dates: this mode discovers
response sessions, not per-stock price eligibility. It never produces prices,
returns, full history, a 180-session calendar or a holiday conclusion.

## Verification And Boundaries

The original dedicated verifier checks the original eight additive files, all existing main blobs,
all inherited suites (including PR62 and PR63), new synthetic cases and the
unchanged current-main replacement/continuity gate on Windows and Linux.
Ordinary test children deny outbound network through the inherited audit hook;
fake transport lifecycle/cold processes never touch public endpoints.

The binding-defect verifier separately binds its current base/head and seven-file
repair scope, preserves all other main blobs, and runs the original 82 discovery
tests plus new binding/schema regressions. Historical PR64 evidence is not rewritten.
The failed discovery's consumed authorization remains consumed and is never
resumed, relabeled or transferred to the corrected endpoint/parser identity.

All four targets remain **not attempted** in engineering. Financial requests,
real discovery, ranking, publication, Latest/state/Portfolio/Ledger/scheduler
mutation are zero. Historical PIT remains UNPROVEN; intraday remains
BLOCKED_EXTERNAL; fallback is false; decision/production eligibility is false.

Next gate: `CONTROL_CENTER_REVIEW_THEN_DISCOVERY_AUTHORIZATION`.

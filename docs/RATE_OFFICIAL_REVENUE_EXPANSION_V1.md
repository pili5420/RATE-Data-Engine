# Candidate Official Revenue Snapshot V1

Scope: candidate official revenue coverage plus existing financial-feature/shadow
refresh. No EPS requests, formal scoring/production activation or source change.
The exact original universe and EPS/gap values, references and observation times
are inherited from a pinned previously delivered feature package. The original
producer and shadow packages are immutable comparison evidence, not rebound.

## Request Plan and Transport

Prepare a new external request root with externally pinned old delivery index and
inventory hashes. Replay existing sources first. For each market TWSE/TPEX and
month 2026-07/08/09, derive missing observation symbols (not undefined zero-base).
Reuse a market-period already containing every universe observation; otherwise
refresh once, with at most six total requests and zero retries. Persist endpoints,
reason, exact universe/windows, EPS/gap hashes, parser/transport identities,
code Base/Head, budgets and new output root BEFORE any request.

Reuse `MOPSHistoricalFundamentalAdapter.fetch_revenue_period/_open`, exact MOPS
receipt retention, `_warmup_revenue_rows` and `validate_revenue_semantics`. A small
strict opener disables redirects and RETURNS HTTPError responses to the existing
capture path, so error bytes are retained but the legacy redirect-follow branch
is never entered. No alternate endpoint, TLS/proxy/DNS alteration or account use.
Reuse DispatchGate and exclusive OS-held writer lock in the NEW request root;
no acquisition/scanner locks are taken in any ancestor. First dispatch uses a
conservative 13-second anchor and each subsequent dispatch waits at least13 after
capture completion; early sleep return must make progress and remaining delay is
rechecked. Dispatch JSON/digest/request/session evidence is saved before outbound.
The reused protocol's historical label does not imply any FinMind request.
Measurement remains CAPTURE_CALL_NOT_HTTP_WIRE_START, not HTTP wire timing.

401/403/429, redirect, network/identity/hash/schema/row failures stop subsequent
requests. Error receipts/raw and traceback are retained. No restart with existing
intents/events or result is allowed, preventing unknown-outcome automatic retry.

## Whole-Response Version Selection

Successful new responses replace the ENTIRE old market-period selection within
the fixed universe, not only missing/improving rows. Outside-universe rows remain
in raw and are listed but never enlarge the universe. Missing old rows are not
backfilled. Save unchanged/added/value_changed/numeric_status_changed/
no_longer_observed with both versions and references. Duplicate/conflicting
symbols, wrong market/month, nonfinite values and malformed numbers fail closed.
Null/UNDEFINED_ZERO_BASE is preserved. Unrefreshed periods explicitly identify old
receipts and keep old times. A failed attempted period has NO selected response,
never silently falling back; later unattempted targets explicitly keep old data.
Such a result is PARTIAL_SOURCE_FAILURE, not a PASS new snapshot. Mixed acquisition
times are not a simultaneous snapshot, official latest or complete revision history.

## Opt-In Bridge and Existing Computation

Only `replay_binding()` receives a three-line opt-in branch for the exact mode
`OFFICIAL_REVENUE_SNAPSHOT_INPUT_V1`. Legacy loader/remainder is unchanged. New
source binding pins snapshot manifest/plan/parent feature identity. Independent
source replay revalidates original EPS/receipts and new exact MOPS bytes/header/
columns/semantics/market membership/dispatch/time; copied values alone are not
source proof. EPS input and gap hashes must match the original package.

Reuse all PR35 feature formulas/windows/Decimal/12-decimal ROUND_HALF_EVEN revenue
mean and PR36 pctl/weights/eligibility/rank/sensitivity. All companies remain;
missing inputs stay null, never smaller denominators or redistributed weights.
New feature producer and shadow execution identities/times are separate from
ancestors. Existing computation executes offline: its new-request count0 is a
COMPUTATION-PHASE count, while source acquisition request count is separately in
the new snapshot/plan. Historical cutoff2026-10-05 remains UNPROVEN.

## Comparison and Engineering

Old308 is the pinned baseline, not a target to force. Derive observation/finite
positions, eligibility entrants/exits/common and market counts. For common firms,
save old/new raw revenue, percentiles, scores and ranks. A sequential fixed-common
population comparison can separate old-population removal, raw-value change with
membership fixed, and new-population addition while new values are fixed. It is
a counterfactual percentile decomposition, not a causal/performance claim; if the
common filtered set has fewer20, mark decomposition unavailable instead of fitting
or attributing all score changes to population. Never infer industry or returns.

Exact-head CI retains188 historical regressions plus new synthetic tests. The new
verifier permits only six new files plus the opt-in source-reader and CI routing
changes. The old feature workflow routes to this current diff verifier when it
exists, otherwise preserves the historical verifier; no historical assertions or
tests are weakened/skipped. Formal code, EPS parser, feature contract, pctl,
shadow spec/weights, active contracts/registry and state are protected unchanged.
Real raw/receipts/values and all actual refresh outputs remain local.

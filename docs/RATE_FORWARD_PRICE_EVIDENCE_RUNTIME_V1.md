# Forward Price Evidence Runtime V1

Single existing observed-forward baseline only. No new snapshot, financial request,
model/contract/weight/pctl/tie change, Production, schedule or alternate source.
Runtime execution is separate from the original baseline/Producer bindings.

## Source And Session

Use registry-authorized TWSE STOCK_DAY_ALL and TPEx mainboard daily close quotes.
Use existing monthly TWSE MI_5MINS_HIST and TPEx indexInfo/inx benchmark products.
The latter expose actual dated sessions; never use weekdays or a holiday guess.
Exact endpoints, methods/parameters, existing parser/module/registry hashes and
runtime Base/Head are captured in an immutable request plan before four initial
same-month requests. Sequence, completion-anchor13 seconds, no redirect/retry or
fallback. Save exact bytes and immutable receipts even on HTTP/schema failure.
The existing market close/date/symbol normalizers and benchmark parser are reused
unchanged (no fabricated OHLC/volume inputs for a close-only bridge); raw date/symbol,
nonfinite/nonpositive/duplicate validation occurs before they can default/drop rows.

All captures occur after13:30 Taipei on the explicit candidate date. Each raw row
also requires observation after its own official close. HTTP time is not the close.
Only benchmark AND same-market daily evidence jointly confirm a session. Missing
expected companies stay in1978; missing close/suspended/unobserved company entry or
required path fails closed via the existing Forward consumer, never carry/zero/late
entry. Invalid finite or identity data fails the whole capture. Date-gaps in the
required daily session archive stop rather than invent the unavailable old closes.

Joint benchmark absence plus an actual daily product reporting only an earlier
date is NO_SESSION_OBSERVED, not proof of HOLIDAY or complete publication. Such
rows are diagnostic only, not stale fallback or post-seal prices. A later benchmark
revealing a previously unobserved session requires that day's real daily evidence;
without it the archive is blocked. Do not silently skip it and choose a later entry.
TWSE/TPEx are evaluated independently and retain separate verified chains.

## Archive And Compatibility

RATE_OFFICIAL_FORWARD_PRICE_ARCHIVE_MANIFEST_V1 opt-in input_mode
OFFICIAL_MARKET_DAILY_FORWARD_INPUT_V1. It binds generated_at,
sessions_complete_through (coverage cutoff, not a completeness/holiday guarantee),
baseline file/hash, snapshot/universe identity, exact1978 company-market roster,
source identities, raw/receipt pins, optional parent manifest and runtime execution.
Session coverage exports expected/observed/valid/missing/invalid symbols. Raw row
index/JSON locator, observed_at/source_validated_at, official trade date and13:30
close are preserved. Unknown aliases/vendors are not admitted. Monthly manifests
without the opt-in mode run the original reader unchanged, covered by all52 tests.
The only updater addition is an opt-in price_source label for daily-market entry;
all original arithmetic, entry/horizon/missing rules and old events remain unchanged.
Later immutable manifests keep old daily receipts; refresh only the benchmark view
explicitly and require an unchanged prefix of already verified sessions. Duplicate
or conflicting daily snapshots fail. No ledger writer creates fake market requests.

## Commands And Trust

scripts/run_forward_price_runtime.py prepare/acquire/apply/verify require exact-clean
runtime Base/Head and external new outputs. Externally trusted checkpoint/hash must
match current heads; baseline JSON must equal the sole immutable snapshot payload.
Prepare does not request; acquire is bounded and cannot automatically restart any
intent/unknown outcome. Acquisition failure retains DEFECT_EVIDENCE, raw and receipt.
Apply invokes scripts/run_provider_shadow_forward.py evaluate; verify uses its cold
source replay path. Both preserve the original binding, compare every preexisting
ledger file/hash, require one snapshot, and produce a new external checkpoint.
Repeat apply uses latest trusted checkpoint, adds no identical event and replays
the same material with no additional HTTP. New heads do not rewrite old checkpoints.

## CI And Deployment Boundary

Existing263 regressions retained plus new runtime synthetic tests on Windows/Linux.
Exact-Base/Head narrow diff protection preserves all formal parsers/contracts and
calculators; only the daily-reader opt-in and necessary CI routing may change.
Manual workflow_dispatch is opt-in on a separately authorized controlled Windows
self-hosted evidence runner; no runner registration/activation or dispatch here.
No schedule trigger. Public hosted CI uploads synthetic evidence only; real raw,
receipts, members, prices, ledgers and checkpoints stay in controlled local storage.
If no actual post-seal session exists yet, report pending entry, not successful
entry freeze or a matured return. First5D can contribute only1/20, never automatic
Gate A PASS. Historical PIT stays UNPROVEN. READY_FOR_REVIEW; do not merge.

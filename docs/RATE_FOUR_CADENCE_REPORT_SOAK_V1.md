# Report Production Soak Separation V1

Change request: `RATE-REPORT-SOAK-SEPARATION-V1`.

## Separate Acceptances

`RATE-FOUR-CADENCE-REPORT-SOAK-V1` is a report/state continuity acceptance,
not CER081 and not authorized intraday feed resolution. Its credit scope is
`PUBLIC_OFFICIAL_EVIDENCE_PARTIAL_VALID_REPORT_SOAK_ONLY`.

`RATE_REPORT_PRODUCTION_SOAK=PASS` can coexist with
`CER081_FULL_PRODUCTION_SOAK=BLOCKED_EXTERNAL`. No report credit is transferred.
All three existing full-soak/completion/production-acceptance blocked flags and
`fallback_allowed=false` remain unchanged. No strategy, ranking, weights,
historical pins or restored acceptance bytes change.

The current CER081 CLI always reads the current external dependency and gives
zero full-soak credit while blocked, even if 12 successful schedule metadata rows
omit their runtime gates. Its pure legacy builder without current governance is
retained for the original historical regression contract only; it is not a live
production approval path. Explicit partial/blocked gates in nested evidence are
also rejected by that builder. Old historical expected results are not rewritten.

## Input And Replay

Run `scripts/run_report_production_soak_acceptance.py` explicitly with:
`--evidence`, independently trusted `--evidence-sha256`, `--state-root`, and a new
external `--output-dir`. It does not fetch, publish, modify a state, or schedule.

The pinned input names an exact predecessor slot and run slots, each with the
canonical state-manifest file/hash, runtime-context file/hash, source-bundle
file/hash and its recorded source validation time. Trust the input hash through
controlled evidence, not by accepting an arbitrary incoming document's own hash.
Keep source files/receipts immutable at their referenced paths.

Only schedule runs count. Manual/dispatch rows are ignored, not relabeled;
the published state manifest must independently prove schedule/main provenance.
Duplicate slots/run IDs, missing or corrupt material, resets, wrong date/cadence,
predecessor ID/hash forks, changed accounts/ledger, fake intraday prices or execution
fail closed. This V1 conservative report-soak mode requires unchanged account and
ledger payloads across the chain; legitimate account changes need a separately
reviewed acceptance extension, never silent acceptance.

The existing runtime calendar defines consecutive trading dates; no new calendar
or holiday inference is introduced. Three complete four-cadence days and two
cross-day links are required. 09:30/12:00 must replay public official raw/receipt
bytes and retain PARTIAL_VALID/blocked/no-execution. 07:30 validates its official
bundle and state binding; 19:30 validates the existing formal EOD closure and
retained 12:00 lineage. No previous-close current quote, Yahoo or MIS fallback.

Source freshness is checked **at the pinned run's recorded validation time**, not
the multi-day audit's wall clock. The existing production source validator gains
an optional audit clock; all existing callers continue using the actual clock.
Raw/receipt/source/date and future-observation checks are not relaxed.

## Engineering And Live Evidence

The synthetic proof uses generated 07:30 transport states, actual 09:30/12:00 and
19:30 CLI processes, publisher and cold report-consumer replay over three days.
It demonstrates validator behavior, not a real 07:30 production run or three live
scheduled days. Synthetic engineering PASS always has live report credit zero.
CI never calls market endpoints. A real report soak still needs three genuine
scheduled days with independently pinned run/state/source evidence.

The exact-head verifier reuses the original strict archive/test harness, preserves
all 131 original regressions, 56 PR42 tests and 8 scheduler-lock regressions, and
adds separate report-soak tests. It verifies unchanged protected Git blobs and
only the three authorized additive dependency fields. The existing CI runs this
strict profile for the new contract instead of applying PR42's historical diff
allowlist to a different CR. No test failure is whitelisted or treated as success.

No live acceptance, Production publication, model/ranking change or merge is
performed by this engineering package.

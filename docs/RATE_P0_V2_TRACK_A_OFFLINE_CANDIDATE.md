# RATE V11 P0 V2 | Track A minimal offline candidate

Owner authorization: AUTHORIZE_RATE_V11_P0_V2_TRACK_A_OFFLINE_ENGINEERING_AND_TRACK_B_GCP_READ_ONLY_PREFLIGHT
Scope: V2_SOURCE_AND_PIT_OFFLINE_CANDIDATE_ONLY
Frozen main parent: 0334d18bde3bbc8ba0176ab2a51a5d07881e2bd7
Unchanged reference PR #224: 199a1f525c2afe2b3ada0453db28bf84f6150e0e
Unchanged reference PR #225: 6df415257ab9a1204d87d8255f80230c126b74ae
NO_AUTO_NEXT: TRUE

## Strict non-production boundary

This candidate is a structural offline model. It performs no real official-source requests and no official-calendar validation. Caller-supplied bytes, timestamps, proof-shaped digests, market calendars and event completeness fields are **UNTRUSTED FIXTURES**. A passing model result is NOT official historical truth, Source-of-Record approval, Clock/Custody qualification or Production.

- DC01 = BLOCKED; SC01 = ACCEPTED_ENGINEERING_ONLY; SC02_RUNTIME = NOT_QUALIFIED.
- P0_D_ADMISSION = BLOCKED; PRODUCTION_CREDIT = 0; CER081_CREDIT = 0.
- The V1 STALE_OR_FUTURE_CATALOGUE gate remains unchanged and binding, including original failures.
- Frozen V1 Freshness, full-market policy and trading-day gate are neither overwritten nor waived.
- Route B 09:30/12:00 public-official PARTIAL_VALID restrictions remain: no current-price trigger, intraday Top30 reranking, Stage/MHE, or AI paper-execution upgrade.
- Two-symbol synthetic test universe is for negative-test behavior, never a Top30 or full-market substitute.
- Source/update date equality, by itself, is neither V1 override nor V2 admission authority.

## Isolated candidate modules

1. src/p0_v2_date_semantics.py: build_source_receipt retains source_update_date_raw exactly as supplied, parses source-update and trading dates separately, requires allowlisted endpoint, HTTP 200, complete byte count, no redirect/fallback, UTC timestamp, and a deterministic fixture digest. Source provenance explicitly remains UNVERIFIED_OFFLINE_FIXTURE; effective_from and publication_time are never inferred from observation.
2. assess_calendar_fixture: structural two-exchange OPEN model with digest-shaped receipts. Neither opening status nor emergency closure is authenticated by the model.
3. src/p0_v2_pit_universe.py: assess_pit_model verifies both-market fixture coverage, synthetic effective intervals, CFI ES ordinary/common equity and normal listing, event ID, synthetic receipt hash, duplicate and transfer conflicts, non-common exclusion, suspension-not-delisting and terminal status. A model PASS always has pit_coverage_status BLOCKED_PIT_HISTORY_GAP and production_permit NOT_ISSUED: synthetic completeness cannot prove historical Source-of-Record completeness.
4. assess_forward_snapshot: a claimed effective date earlier/later than its nominal observed Taipei date is rejected. A same-day fixture yields OBSERVED_ONLY_OFFLINE and never PIT PASS.

No module connects to V1 live admission, production Source/State/Ledger, Scheduler or Cloud resources. No prior 19:30 failure is reclassified.

## Negative test matrix

- Source Date mismatch and equality both withheld from official authority.
- Incomplete HTTP response, failure, redirect, fallback and unallowlisted endpoint rejected.
- Missing classification date, future nominal update date and naive observed timestamp rejected.
- Missing/closed/unknown exchange calendar blocked.
- Missing synthetic history, market coverage, effective interval and event ID blocked.
- Cross-market duplicate/transfer, CFI unknown, non-common passed as common, delisting outside the target interval, incomplete symbol list blocked.
- Suspension does not silently imply termination.
- Prospective observation cannot backfill retrospective eligibility.
- Every successful fixture still emits no Production permit or CER-081 credit.

Targeted validation: python -m unittest tests.test_p0_v2_offline -v

## Open authority gaps and independent review

- Official TWSE/TPEx definition and authoritative effective interpretation of the ISIN Date Stock Updated label.
- Complete date-effective event history covering listing, delisting, market transfers, CFI changes and suspensions/resumptions.
- Independently authenticated historical observation, event completeness, correction/revision cutoff and exchange closure authority.
- Trusted acquisition clock, immutable raw receipts, Store and independent verification.
- Formal Owner Change Control before any replacement of Frozen V1 or adoption of Source Authority V2.

Track A completion is READY_FOR_INDEPENDENT_P0_V2_TRACK_A_ENGINEERING_REVIEW only after PR exact-head Linux/Windows CI success. The independent reviewer must check this candidate's fail-closed limits; no auto-merge or Production.

NO_AUTO_NEXT=TRUE — stop at one bounded offline engineering batch.

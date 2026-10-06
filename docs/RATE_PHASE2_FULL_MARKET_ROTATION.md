# RATE Phase 2 Full-Market Rotation Review

## Scope and Authority

This additive PR prepares a **read-only candidate pipeline**, not a production
activation. It does not wire the existing scheduler or publisher to the candidate
pipeline. Existing production logic and all existing tracked files remain
byte-identical to main commit `bb48834cb9cbbb637aecffef9e92fe543d62f1d2`.

The candidate contract separates these authorities:

| Field | Authority |
| --- | --- |
| continuity_baseline_source | PREVIOUS_VALIDATION_PASS_DECISION_STATE_SHORT_TERM_TOP30 |
| candidate_universe_source | FULL_TAIWAN_ELIGIBLE_MARKET_UNIVERSE |
| ranking_refresh_source | FULL_MARKET_SCAN |

The committed contract is intentionally blocked until Control Center supplies a
complete eligibility policy, its ID/hash, and inclusion/exclusion criteria.
It is not an approved Taiwan market catalogue. Catalogue input must contain
both official market inventories, per-record eligibility decisions, complete
record counts and hashes, current trading-date binding, PASS source/freshness/
validation, and no fallback. Eligible symbols must exceed 30 and include symbols
outside the canonical previous Short-Term Top30. Bootstrap/previous-30-only and
incomplete/stale catalogues are rejected, not substituted.

## Canonical Continuity Blocker

The actual main rebaseline slot `2026-10-02/19:30` loads through
`production_live_state.load_live_state` with state ID
`rate-state-baa7113253efcaf5d448e431` and state hash
`baa7113253efcaf5d448e4319318e070da6f6a680d55303e209cd3d64d2d7fec`.
Its persisted decision does **not** contain `short_top30`, `top50`, `long_top30`,
or ranking records. Consuming it as the mandated previous ranked decision fails
closed with `PREVIOUS_DECISION_SHORT_TOP30_MISSING`.

No seed-derived ranking, first-refresh exception, parallel state schema, or live
state change is introduced. Control Center must identify a canonical ranked
predecessor or explicitly authorize the first-refresh continuity rule before
production integration can proceed.

## Ranking and History

For 19:30 candidate evaluation, complete eligible-symbol histories are bound to
the catalogue and contract. Stock and market-matched benchmark inputs require
180 official EOD sessions. Institutional history, TDCC periods and MOPS
fundamentals must support the existing seven-session Stage feature replay.
Missing warmup returns `HISTORICAL_WARMUP_REQUIRED`; no data is fabricated,
filled from stale inputs, or fetched from an alternate provider.

Existing owners perform historical technical/institutional/Rotation derivation,
Stage evidence, M7/MHE/Smart Money/Fundamental calculation and ranking. Existing
formulas, tie-breaks and Stage transition definitions are untouched. As in the
existing acceptance callers, Top50, Short-Term Top30 and Long-Term Top30 each
rank the full eligible input rows. Filtering Top30 through Top50 would change
the approved selection scope and requires separate strategy approval.

Current `production_snapshot_id`, current `input_snapshot_id`, and the canonical
predecessor's state ID/hash are separate bindings; none substitutes for another.
Stage evidence consumes the current input snapshot and canonical prior state.

07:30 consumes a canonical full-market PASS 19:30 predecessor without another
scan. It rejects an explicitly selected older slot when a newer slot exists.
09:30/12:00 retain the authorized intraday fail-closed gate and do not call
full-market derivation. Their read-only review currently verifies predecessor/
feed eligibility and preserves rankings; it does not implement incremental
production account/state updates.

## Verification and Non-Mutation

Synthetic fixtures are ENGINEERING-only, never authoritative market evidence.
They exercise 60 candidates (30 outsiders), complete Top50/30/30 outputs,
ranking-driven entry/exit, unchanged-ranking/no-forced-turnover, canonical
persisted-slot consumption, incomplete inputs, warmup, source rejection and
intraday gates. Candidate results are always non-authoritative and cannot
publish or mutate live state, accounts or ledger.

The CLI can only write `RATE_PHASE2_FULL_MARKET_ROTATION_REVIEW.json` outside
protected production namespaces. The PR-only CI checks exact PR head identity,
frozen ranking/source/state owners and byte-identical existing tracked files.
No production workflow is dispatched. Existing bootstrap, authorization and
canonical material files are not edited.

## Remaining Production Work

1. Approved eligibility policy and authoritative full-market catalogue.
2. Explicit first-refresh continuity authority for the rankless rebaseline.
3. Official full-market historical/current data-plane materialization and
   source receipts; no actual full-market warmup acceptance is claimed here.
4. After those gates pass, approved normal-runtime integration replacing the
   seed-only path, full-market source/manifest bindings and read-only production
   acceptance. Current production source/scheduler callers are untouched and
   therefore are **not** yet Phase 2 normal-production implementations.

**Production activation: BLOCKED.** This PR is for review of the isolated
candidate implementation and blocking evidence only.

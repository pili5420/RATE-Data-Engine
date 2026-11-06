# RATE V11 Track B — Prospective Rebaseline / New Boundary (DESIGN ONLY)

Authority: AUTHORIZE_RATE_V11_TRACK_B_REBASELINE_DESIGN_AND_TRACK_C_SCHEDULER_POC_DESIGN_ONLY
Controlling main at design start: `0334d18bde3bbc8ba0176ab2a51a5d07881e2bd7`
Disposition: DESIGN_CANDIDATE_ONLY / NOT_EXECUTION_APPROVED

## Problem, source custody and non-credit boundary

The committed canonical pointer `artifacts/RATE_PRODUCTION_STATE_LATEST.json` identifies 2026-10-02 19:30, `CONTROL_CENTER_REBASELINE`, `scheduled_soak_credit=false`, authorization `CC-RATE-REBASELINE-20261002-1930-V3`. This is not a valid Nov 2026 scheduled predecessor. The exact authorized 2026-10-02 material and its single-use permit may not be retargeted or replayed. `src/phase2_production.py:latest_predecessor` requires preceding legal trading day's 19:30 for 07:30, same-day 07:30 for 09:30 and same-day 09:30 for 12:00. No fabricated links/backfills.

### Required authoritative custody search (not completed in this design PR)

- Enumerate GitHub schedule runs, job attempts, immutable artifacts, commits and canonical manifests for all missing precise predecessor slots; independently match source run ID/event/workflow/head/attempt/manifest hashes.
- Check archived State/Portfolio/Transaction Ledger and source snapshot custody without treating `workflow_dispatch`, historical rebaseline, or unverified archives as schedule credit.
- Deliver a source-custody matrix per slot: `FOUND_VERIFIED / NOT_FOUND / CONFLICT / INACCESSIBLE`; any unresolved ambiguity is BLOCKED. Do not assert irreplaceability solely from absent tracked files.

## Proposed future new-boundary contract (requires separate owner adoption)

1. Assign new prospective `baseline_id`, exactly one legal `trading_date` and `cadence=19:30`, and an explicit historical-chain-break declaration; keep the former terminal state ID/hash as immutable historical reference, not as a fabricated predecessor.
2. Require a new `RATE_PRODUCTION_SOURCE_BUNDLE` bound to selected slot with official Route B source provenance, `validation_status=PASS`, freshness/completeness PASS and verified 30/30 TWSE/TPEx records. A current-day 19:30 source must not be made up from historical 10/02 data.
3. Require `RATE_PRODUCTION_REBASELINE_DECISION_STATE`, `CONTROL_CENTER_REBASELINE_ROY_OPENING_STATE`, `CONTROL_CENTER_REBASELINE_AI_OPENING_STATE`, `RATE_LEDGER_REBASELINE_BOUNDARY`, and `RATE_PRODUCTION_REBASELINE_MANIFEST`; cryptographically bind exact bytes and manifest, expected State ID/Hash, source snapshot IDs, owner-authorized account/portfolio opening evidence and ledger discontinuity.
4. Roy positions/cash/valuation must be owner-authenticated with no synthetic holdings. AI opening capital/PnL and ledger must explicitly not import irrecoverable transactions, invent fills or claim historical continuity. `POST_REBASELINE_ONLY` and `HISTORICAL_RECOVERY_SOURCE_IRRECOVERABLE` may only be used when supported by separate custody determination.
5. New `control/rebaseline_authorizations/<new-id>/RATE_PRODUCTION_REBASELINE_AUTHORIZATION_MANIFEST.json` must bind approved commit, one-time scope, exact file hashes, exact date/cadence/baseline/state, dispatch prohibition/permission as explicitly decided, `scheduled_soak_credit=false`, `acceptance_counter_reset=false`. No reuse of V3 authority.
6. Design for atomic staging, hash/readback, idempotent consumed-permit rejection, conflict rejection if any newer canonical slot exists, no fallback, no historical ledger rewriting, and fail-closed rejection of incomplete partial publication.
7. Do not open `CURRENT_PRODUCTION` until separate post-merge official 09:30→12:00 activation evidence PASS; only official post-session event=schedule runs may count.

## Contract-gap matrix (current code, no changes authorized)

| Existing authority or code | Present expectation | Design risk / required decision |
|---|---|---|
| `scripts/bootstrap_production_rebaseline_state.py` | Exact owner manifest, committed approval ancestry, hashes, 30/30 source, Roy 10 positions, AI opening 1,000,000 with empty positions, ledger `REBASELINE_OPENING_BALANCE` | New evidence may differ: request explicit approved contract changes; do not weaken validator to force admission |
| `src/phase2_production.py` + full-market first refresh policy | 07:30 previous legal trading-day 19:30; First Refresh exact predecessor State ID/hash/date and single-use guard | Need independent impact review of new boundary, ranking-first-refresh authority and same-day cadence; no authority bypass |
| `docs/contracts/RATE_V11_PRODUCTION_ACCEPTANCE_SESSION_V1.json` | Activation PASS before Session; 3 trading days / 12 schedule attempts and continuity | Old runs and bootstrap never receive credit |
| `config/RATE_ROUTE_B_ACTIVATION_BASELINE_V1.json` | Code `0b463dcc04b21f9d1b56f10e6c6e5605a4e55bdf` and Git-derived binding `0334d18bde3bbc8ba0176ab2a51a5d07881e2bd7` currently latest main | Preserve unchanged; any later merged functional change invalidates binding until fresh re-freeze |

## Offline regression / proof specification (not an execution authorization)

B01: wrong baseline ID/date/cadence/hash fails. B02: missing source freshness, coverage<30/30, or paid/fallback source fails.
B03: changed Roy/AI portfolio or ledger not matching state fails. B04: duplicate/consumed permit or tampered approval commit fails.
B05: incomplete atomic commit/readback fails closed, with no pointer advance. B06: newer live state or conflicting slot fails.
B07: no scheduled-soak/Production/CER081 credit on manual rebaseline. B08: subsequent 07:30 requires correct previous legal 19:30.
B09: existing first-refresh guard cannot be bypassed. B10: post-session cross-day continuity, ranking and transaction ledger must be independently checked.

### Work independent acceptance package
Confirm exact-head scope restricted to this documentation, source search/unknowns honestly recorded, contract-gap completeness, no workflow/config/state edits, and a concrete Owner decision list. Existing CI success does not prove source-custody completeness. No merge until explicit Control Center approval.

### Owner decisions remaining
B-D1: recovery of authentic historical canonical sources vs prospective new-boundary design; B-D2: exact target date/cadence and approved source; B-D3: owner-authenticated Roy/AI opening valuation and ledger boundary; B-D4: any first-refresh / rebaseline contract change; B-D5: one-use execution permit and independent acceptance.

`NO_PRODUCTION_MUTATION=TRUE`, `NO_BACKFILL=TRUE`, `PRODUCTION_CREDIT=0`, `CER081_CREDIT=0`, `NO_AUTO_NEXT=TRUE`.

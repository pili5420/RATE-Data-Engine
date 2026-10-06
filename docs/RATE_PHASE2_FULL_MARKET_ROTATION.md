# RATE Phase 2 Full-Market Production Integration

PR #24 stays Draft. No production dispatch or merge is authorized by this PR.
The approved authority is `CR-RATE-PHASE2-ELIGIBILITY-AND-FIRST-REFRESH-V1`.
Its canonical policy hash is
`94b341554c3c2b20e8d4cc19bb1b9e454b92d2fa6b50e97f78dd70ef18f78b9a`.

## Eligibility, Independent From Data

The official ISIN security catalogue supplies CFI classification for both markets:
[TWSE listed](https://isin.twse.com.tw/isin/e_C_public.jsp?strMode=2) and
[TPEx listed](https://isin.twse.com.tw/isin/e_C_public.jsp?strMode=4).
The TPEx list is the official OTC classification published by the TWSE ISIN service,
not a third-party provider. Each also binds an official company-metadata receipt:
TWSE `t187ap03_L` and TPEx `mopsfin_t187ap03_O`.

CFI ordinary/common equity (`ES`) with normal listed/OTC classification is eligible.
TWSE's Innovation Board is a listed board, not an availability-based exclusion.
Company metadata is reconciled and reported, never used to exclude a classified
common equity. For example, TDRs in company metadata remain non-common equity;
an ISIN-classified eligible symbol missing issuer metadata remains in the universe.
Missing required trading/feature inputs then fail closed for the whole run.

All securities, including exclusions, are retained with type, market, ISIN, CFI,
eligibility and reason. ETF/ETN, warrants, bonds, fund units, preferred, rights,
structured/non-common and non-normal listing records are not eligible.
There are no symbol length/range heuristics, seed lists or data-availability filters.
Catalogues bind current as-of/date, policy hash, two official receipts, record counts,
content hashes and PASS source/freshness/validation. Historical backdating of the
current catalogue, incomplete catalogues, duplicates and stale universes fail closed.

## Runtime Paths

The four scheduler cron definitions are unchanged. Their normal runtime now uses:

1. `resolve_production_runtime_context.py --phase2`: canonical persisted predecessor.
2. `build_production_source_bundle_from_official.py --phase2`: full-market acquisition
   at 19:30; canonical ranked-state consumption at 07:30; authorized-only incremental
   input at 09:30/12:00. No intraday full-market rescan.
3. `run_phase2_production.py`: source, approved Thin Work manifest, canonical lineage
   and account validation; prepares material in the runtime namespace, not live state.
4. Existing source publisher followed by canonical state publisher `--phase2`.
   Only a successful MAIN schedule commits pointers and new immutable artifacts.

MAIN authority, numeric Actions run/job identity and current commit are required.
Dispatch runs can prepare audit material but cannot publish live state/pointers.
The source/Thin-manifest publication gate runs before the state publisher; failed
input or manifest gates therefore cannot advance Production State LATEST.
Old 30-record validator APIs remain available for existing audit regressions, but
their MAIN publication CLIs reject seed-only normal-production authority.

The additive full-market source version is
`RATE-FULL-MARKET-PRODUCTION-SOURCE-BUNDLE-V1`: coverage is the entire bound eligible
catalogue, never an arbitrary count. The approved Thin Work manifest contract is
unchanged. Current input/production snapshots and previous state/snapshot lineage
are independent bindings. Publication retains exactly five write targets; payload
references remain metadata, never another write target.

## First Refresh and Canonical Continuity

`FIRST_FULL_MARKET_REFRESH_AUTHORITY` only admits the exact rankless canonical
`2026-10-02/19:30` predecessor:
`rate-state-baa7113253efcaf5d448e431`, hash
`baa7113253efcaf5d448e4319318e070da6f6a680d55303e209cd3d64d2d7fec`.
The canonical loader validates persisted material, manifest and V3 consumption
evidence unchanged. No previous ranking is synthesized from the rebaseline seed.

The first PASS decision marks `consumed=true`, `completed=true` and turnover
`NOT_APPLICABLE_FIRST_FULL_MARKET_REFRESH`. Entry/exit comparisons are null, not a
fabricated 30-to-30 turnover. Subsequent states carry the immutable first receipt
and use `PREVIOUS_VALIDATION_PASS_DECISION_STATE_SHORT_TERM_TOP30`. Wrong IDs/hashes,
reuse, corrupt persisted slots or an older predecessor cannot pass.

Roy and AI account values are copied exactly. The existing approved historical
ledger boundary is retained verbatim; the first ranked state adds only an empty
post-boundary `transactions` list, not a reconstructed opening transaction.
Subsequent ledgers are copied exactly. The rebaseline slot, opening materials,
V1/V2/V3 authorizations, consumption evidence and bootstrap implementation are untouched.

## Warmup and Frozen Owners

Every eligible symbol requires 180 aligned official stock/benchmark sessions,
26 institutional sessions, TDCC periods, MOPS disclosures and seven-session Stage
replay. The bounded existing stock/benchmark materializers accept the full catalogue,
not their retired top-level seed entrypoint. The independent current-day official
daily response must pass before historical inputs are consumed.

Existing institutional and TDCC owners cover every eligible symbol. Existing MOPS
period acquisition and revision-aware store/selector are reused for distinct months
and quarters; missing disclosures fail `HISTORICAL_WARMUP_REQUIRED`.
History lives in a separate `data/production/full_market_history` namespace, never
the rebaseline material namespace. It is not a substitute for current-day input.
There is no third-party, synthetic, stale-universe or seed fallback.

Existing technical, Stage, Rotation, M7/MHE, Smart Money, Fundamental and ranking
owners are byte-identical. Top50, short30 and long30 each retain the existing full
candidate selection scope and tie-breaks. Identical material hashes may reuse a
calculation within one process; this is not source caching or fallback, and canonical
predecessor/authority validation always runs again.
Freshness uses the existing matrix owner and tolerance, evaluated after acquisition
and derivation. Source retrieval, acquisition completion, evaluation and generation
timestamps remain distinct. True future and stale receipts still fail closed.

07:30 requires the latest legal prior-day PASS 19:30 ranked state without scanning.
Intraday retains `EXTERNAL_AUTHORIZED_INTRADAY_FEED_DEPENDENCY`; feed metadata and
payload hashes must bind the canonical predecessor. No absent-feed workaround exists.

## Acceptance Evidence and Remaining Gate

Read-only official catalogue evidence for 2026-10-06 contains 1,978 eligible symbols:
TWSE 1,085, TPEx 893. It is outside the repository's production namespaces and is
not a MAIN acquisition/refresh receipt. Existing seed history covers only 30 of
those eligible symbols at 180 sessions; 1,948 remain unmaterialized.
The dedicated full-market store is not yet materialized (0/1,978). Seed history
does not carry normal-production universe authority.

PR/unit CI uses clearly labeled engineering fixtures in temporary namespaces.
Fixtures prove 60 candidates, Top50/30/30, ranking-driven entry/exit, exact first
authority, subsequent canonical continuity, account/ledger preservation, no forced
turnover and fail-closed/no-mutation negatives. They are NOT official warmup or
authoritative production ranking evidence.

Actual all-symbol official warmup, complete current-day inputs and the first MAIN
ranked refresh remain acceptance gates. No production activation, live-state write,
Production State LATEST update, merge, bootstrap or Work Phase B dispatch is performed
for this implementation/review. Final status remains BLOCKED until those required
acceptance inputs/evidence exist.

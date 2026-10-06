# RATE Phase 2 Historical Warmup Bootstrap

This is a standalone data-plane PR from MAIN `bb48834cb9cbbb637aecffef9e92fe543d62f1d2`.
It does not include PR #24's scheduler activation. PR #24 stays Draft and unchanged.
No merge, MAIN warmup dispatch, production activation or Work Phase B occurs in review.

## Eligibility and Official Owners

Authority: `CR-RATE-PHASE2-ELIGIBILITY-AND-FIRST-REFRESH-V1`, policy hash
`94b341554c3c2b20e8d4cc19bb1b9e454b92d2fa6b50e97f78dd70ef18f78b9a`.
The official CFI catalogue and approved policy are byte-identical to PR #24 support;
no PR #24 production runtime, scheduler or state publication code is imported.

Official classification: TWSE ISIN listed (`strMode=2`) and TPEx listed (`strMode=4`)
published by the official TWSE ISIN service. Official issuer metadata is reconciled,
not used as an availability-based eligibility filter. Long/different symbol codes
are not screened by length/range; official CFI common equity and normal listing decide.
The requested scope is exactly TWSE 1,085 + TPEx 893 = 1,978. Changed official counts
fail `CATALOGUE_COUNT_CHANGE_REQUEST_REQUIRED`, never a silent universe reduction.

The existing owners remain byte-identical:

- Stock and benchmark: TWSEAdapter, TPExAdapter, existing bounded month normalizers
  and PersistentHistoricalStore retention (220 sessions).
- Institutional: existing CER-072 date-identity T86/TPEx daily history and arithmetic
  validation, 26 completed sessions for the existing FI/IT/FC and Stage lookbacks.
- TDCC: existing historical form query, official available-period selection and
  tier normalization; five periods as-of each of seven Stage replay sessions.
- Fundamental: MOPSHistoricalFundamentalAdapter and revision-aware
  FundamentalHistoryStoreV2 selectors, at least three revenue periods and eight
  quarterly EPS records. Six distinct prior months and ten closed quarters are
  queried; disclosure dates are never replaced by retrieval times.
- Stage: existing build_stage_feature_histories over the full eligible cross-section,
  seven replay sessions. No shard-specific percentiles, ranking or formula change.

Source overrides, accepted seed cross-sections, local staging stores, alternate
providers and synthetic/previous-universe/stale data fallback are not allowed.
Existing official owners' approved transport/representation paths are preserved;
these are not permission to replace a failed dataset with another provider or cache.

## Durable SSOT and Identity

The authoritative store is the dedicated Git branch `rate-production-history`, not
runner disk, Actions artifacts or a cache. Every acceptance receipt names the exact
storage Git commit SHA. That immutable Git object plus the manifest's SHA256 bindings
defines authority, rather than the moving branch HEAD. No `LATEST` pointer is created.

The store is append-only through a sole writer, with no modifications/deletions,
force push, reset, rebase, merge or MAIN push. Non-fast-forward races fail closed.
An external force rewrite of the branch is not accepted as a replacement identity:
reload requires the exact commit and ancestry, then all hashes and provenance.
Operational branch protection is recommended before controlled MAIN dispatch.

Layout:

```text
catalogues/<canonical-sha256>.json
plans/<plan-id>.json
materials/<compressed-byte-sha256>.json.gz
progress/<plan-id>/<symbol-sha256>.json
shards/<byte-sha256>.json
manifests/<byte-sha256>.json
snapshots/<snapshot-id>.json
reports/<byte-sha256>.json
```

JSON is ASCII, sorted keys, compact separators, finite numeric values and a trailing
LF. The catalogue's own approved content hash retains its original canonical owner;
history byte digests are separately named. Gzip has no filename or wall-clock mtime.
Stored compressed bytes and decompressed canonical bytes both have SHA256 references.
The checkout disables CRLF conversion before reading immutable files.

A plan binds catalogue, as-of, previous legal completed trading day, policy/contract,
owner byte fingerprints, initial MAIN run/commit identity and deterministic shards.
Each new symbol material independently binds its actual acquisition MAIN run/commit;
resume never labels a later download as the original plan run. Transfer artifact
names also bind run attempt to prevent rerun naming collisions.
Resume must supply the exact durable plan ID and same as-of. Old-as-of historical
resume is historical acquisition, never a stale current-day universe fallback.
A changed owner fingerprint, policy, catalogue, checkpoint or material is a blocker.
Previously verified records are source-bound persisted history, not cache authority.

The snapshot ID hashes the complete coverage core including all symbol material
hashes. Its manifest separately binds plan, catalogue, every material and shard,
per-symbol coverage, owner fingerprints and full-cross-section Stage replay material.
Reload checks exact commit ancestry, all hashes, every symbol/domain, shard membership,
snapshot identity and the existing Stage replay result. Reload is read-only.

## Bounded Workflow and Resume

`rate_full_market_history_bootstrap.yml` is manual dispatch on MAIN only. Every
CLI command also checks MAIN ref/event, numeric run ID, exact checked-out source SHA,
MAIN ancestry, repository identity and no source override. PR fixture execution is
not allowed through this CLI. All output roots are outside the code checkout.
It requires GitHub Actions execution and verifies the actual Actions run record:
exact warmup workflow path, MAIN head, dispatch event, attempt and source SHA. The
resulting GitHub execution evidence is persisted in plan/material authority.

1. Plan job: current official catalogue, or exact previously persisted plan. With the
   approved counts there are 22 TWSE + 18 TPEx shards, each at most 50 symbols.
2. Acquisition: at most four parallel shards; each shard acquires symbols sequentially,
   max 12 official stock/benchmark months and 2,400-second acquisition budget.
   Outer transport retry is at most three attempts with 1/2-second backoff for retryable
   transport/JSON failures. Nonretryable HTTP/schema failures stop; existing owner
   timeout/retry/circuit policies remain bounded and unchanged. Budget exhaustion
   forbids another request; in-flight owners retain their own bounded timeout.
   Within a single shard/process, repeated identical official benchmark or market-wide
   institutional queries reuse the successfully fetched response with its original
   receipt timestamp/hash. Failed calls never populate this memo; it is neither
   persistent SSOT nor a fallback after a failed request.
3. Each completed symbol is validated and checkpointed independently. A failure does
   not exclude it from eligibility or cancel other shards. Seven-day Actions artifacts
   transfer validated progress but are never the persistent SSOT.
4. A single `always()` persistence job validates every incoming material before adding
   it to the history branch. Hash-corrupt inputs fail before durable publication.
   Verified partial progress may be committed for resume, but coverage remains
   `FAIL_CLOSED/HISTORICAL_WARMUP_REQUIRED`; no PASS snapshot is created.
5. Only 1,978/1,978 complete symbols permit the full-cross-section Stage owner and final
   snapshot/manifest. The writer verifies deterministic reload, pushes the dedicated
   branch, verifies remote commit, and returns exact storage SHA/identity. A failed
   source, Stage, material or Git gate never grants production acceptance.

The dispatch interface is `as_of` (official catalogue date) and optional
`resume_plan_id`. Stock and benchmark sessions are strictly before this date and
must end on the previous legal completed trading day. No incomplete current session
or effective/trading-date rewrite is used. Every EOD/institutional session must also
pass the existing unchanged trading calendar; weekend/holiday rows cannot count
towards coverage. A symbol with fewer than 180 official
aligned sessions, including a new listing, remains eligible but blocks acceptance;
no fabricated pre-listing history is permitted.

## Snapshot and Manifest Contracts

`RATE_FULL_MARKET_HISTORY_SNAPSHOT` / `RATE-FULL-MARKET-HISTORY-SNAPSHOT-V1`:
snapshot ID, as-of/trading date, completed-through date, plan/policy ID/hash,
eligible/market counts, six coverage domains, minimum stock sessions, all material
hashes, missing/failed symbol lists, validation PASS and fallback false, manifest ref.

`RATE_FULL_MARKET_HISTORY_MANIFEST` / `RATE-FULL-MARKET-HISTORY-MANIFEST-V1`:
snapshot/core hash, plan/catalogue hashes, owner fingerprints, SHA256 of each shard
and each symbol material, per-symbol domain counts, Stage replay reference,
storage authority, validation PASS and fallback false.

Any missing domain, incomplete catalogue, wrong symbol/market, hash mismatch,
duplicate, stale/future completed date, future disclosure/receipt, insufficient
history, unauthorized provider or altered lineage fails closed. Eligible symbols
are never filtered because of these failures.

## Review Versus Production Acceptance

PR CI uses clearly marked engineering fixtures and local temporary bare Git remotes
to prove full-domain validation, partial progress, exact reload, append-only storage,
resume/idempotency, full-cross-section Stage replay, retries and negative gates.
All 323 existing MAIN files are compared byte-for-byte, without integration exceptions.
CI checks workflow syntax and exact head, and never runs the MAIN warmup workflow.

These tests are not real 1,978/1,978 warmup evidence. Actual snapshot ID, storage commit
and MAIN Actions acceptance remain absent until a separately approved merge/release
and controlled MAIN dispatch. No local or PR CI data receives production warmup credit.

Real live state, Production State LATEST, Roy/AI Portfolio, Ledger, rebaseline,
V1/V2/V3 authorizations/consumption, bootstrap, production schedulers, OIS and Work
remain unchanged. No Phase 2 ranked state is created by this data bootstrap.

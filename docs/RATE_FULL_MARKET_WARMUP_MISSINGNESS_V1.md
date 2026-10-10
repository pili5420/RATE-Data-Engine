# Full-Market Warmup Missingness V1

CR: `RATE-FULL-MARKET-WARMUP-MISSINGNESS-V1`.

This opt-in acceptance concerns universe inventory only, not execution of the
legacy Production warmup. Its artifact is not a Decision State or source bundle.
The implementation lives in `scripts/warmup_inventory_acceptance.py`, an
offline engineering layer, not a new `src/` Production entry. This preserves
Phase G's existing source-entry isolation regression without changing its test.
No existing consumer imports this engine. Existing formal warmup, ranking,
publisher and provider activation gates remain unchanged.

## Separate Acceptance Layers

- `FULL_MARKET_UNIVERSE_ACCOUNTING`: PASS only for the exact pinned historical
  catalogue, all 1085 TWSE and 893 TPEx issuers retained, with explicit approved
  financial evidence states and replayable hashes.
- `FUNDAMENTAL_HISTORY_STATUS`: EPS/revenue completeness and formal input
  readiness separately. An inventory-complete issuer can remain financially
  incomplete or formally unauthorized.
- `MODULE_READINESS_STATUS`: independent Phase G owner verdicts, never a
  global ready flag.
- `RANKING_ELIGIBILITY_STATUS`: subgate verdicts only. Counts do not authorize
  the ranking consumer, calculate a score, or change ranking populations.
- `PRODUCTION_PUBLICATION_STATUS`: NOT_AUTHORIZED.

No combined `FULL_WARMUP_PASS` is emitted. No missingness exception grants
provider, first refresh, ranking or Production acceptance.

## Trusted Owner Evidence

The input is the existing Phase G source-readiness projection, pinned using
the hash in its independently retained delivery index. The exact historical
universe is loaded by the existing `load_universe` verifier. Each owner's
verdict is reconstructed through `issuer_eligibility`; all projected readiness
and missing reasons must agree. Reference bytes are rehashed. This layer
checks certificates, not new financial calculations or source parsing.
The caller must also verify the certificate's transitive source manifest;
reference hashing alone is not a replacement for the original source owner's
semantic replay. The local verification package records that check separately.

Only COMPLETE, MISSING_REQUIRED_PERIOD and revenue UNDEFINED_ZERO_BASE are
accepted inventory states. INVALID_EVIDENCE, absent owner verdicts, absent
missing reasons, unsupported period states or corrupt evidence fail closed.
Technical owners may remain NOT_EVALUATED without acquiring fabricated scores.

Original issuer evidence and partial-history references are preserved verbatim,
including original raw/receipt/locator/time identities. EPS values remain in
their immutable, pinned source artifacts. No values are rewritten or replaced;
valid history is not discarded because another quarter is missing.

## Continuity And Reproduction

An optional independently pinned context is copied unchanged. If omitted, the
artifact explicitly says NOT_SUPPLIED_NOT_INITIALIZED and does not invent any
Decision State or account. A subsequent inventory binds its previous snapshot
and preserves its history prefix. Changes to account context, issuer history
or Decision State identity fail closed instead of silently resetting state.

Cold consumers first check the independent file pin, then `verify_inventory`
replays source references and recomputes subgate verdicts, totals and layer
statuses. Generation time cannot precede the verified input certificate.
Identical input produces identical core identity; actual generation time is
outside the core. Write to a new external directory only:

```text
python -B scripts/build_warmup_missingness.py
  --projection <prior-projection> --projection-sha256 <trusted-delivery-pin>
  --universe-evidence <historical-plan> --universe-sha256 <trusted-plan-pin>
  --universe-commit <original-catalogue-commit> --output-dir <new-external-dir>
  --source-manifest <prior-transitive-source-pins> --source-manifest-sha256 <trusted-pin>
```

Optional `--context/--context-sha256` and `--previous/--previous-sha256` pairs
require independent byte pins. This command has no network or live-state path.
The mandatory source manifest is a path-to-{bytes, sha256} mapping from the
prior independently pinned delivery; every entry is checked, without exclusions.
Public CI uses synthetic certificates only. Real evidence stays local.

Historical PIT remains UNPROVEN, fallback false, provider production eligibility
false, original eight-quarter acceptance credit zero. Any activation requires a
separate approved CR. PARTIAL_VALID runtime and Report Soak/CER081 separation
are not changed by this inventory policy.

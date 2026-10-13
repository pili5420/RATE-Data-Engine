# Fundamental Consumer Binding V1

CR: `RATE-L-FUNDAMENTAL-RANKING-CONSUMER-BINDING-V1`.
Base: `e5953fa3ff7123a28d85ec6c4f361c25da9bc4ab`.

This opt-in adapter reads only the accepted dedicated Fundamental Latest and
its immutable First Refresh snapshot. It does not activate ranking, publish
Production, acquire data, or mutate state. All seven files are additive; every
existing main blob, including the V1 engineering eligibility contract, is frozen.

## Trust And Lineage

The production contract pins the Control Center accepted Latest identity,
snapshot content identity, snapshot file-byte identity, universe identity, and
Phase K acceptance-package hash. A caller also supplies an out-of-band SHA256
for its private path binding. Content hashes and file-byte hashes are distinct.
No manifest is trusted merely because its own hash recomputes.

The existing committed-reader checks the pointer, commit status and object
bytes. The adapter additionally verifies snapshot semantic identity, exact
1978 membership/markets against the accepted universe hash, original producer
binding, and Phase K acceptance. The acquisition directory is provenance-only,
never an alternative scoring input: its config, deterministic request plan,
event chain, intent hashes/bindings, immutable observation IDs, raw/receipt
hashes, timestamps and row identities must match the accepted evidence index.
Provider schema/source semantic replay was accepted in the separately pinned
Phase K package; this adapter does not implement another provider parser.

Every issuer verdict retains the complete accepted feature inputs, missing
reasons, input-row hash/locator, and four acquisition references (its EPS request
and the market's three revenue requests), including event/intent/raw/receipt
references. Partial valid history and official undefined-zero-base values remain
unchanged. Legitimate missingness is not a source-integrity failure.

## Calculation And Time

EPS arrays follow 2026Q2 through 2024Q3, newest first. Revenue follows
2026-09, 2026-08, 2026-07. Decimal conversion performs no adapter rounding.
All 1978 rows are passed to the unchanged `calculate_fundamental()` owner,
which alone excludes incomplete inputs and selects its percentile population.
Its `pctl()` float conversion, weights and rounding remain unchanged. The
owner's internal four-quarter sum is not promoted to official or common-share
TTM; these are provider-defined unadjusted quarterly values.

Verdict `observed_at` and `validated_at` retain source timestamps;
`input_available_at` includes source first-seen times and accepted publication.
Consumer generation/verification timestamps are separate envelope metadata,
not historical availability. Core content identity excludes these run times.
Code identity uses LF-normalized source hashes for Windows/Linux equivalence;
the envelope separately records exact current file-byte hashes. Evidence bytes
are never normalized. Original producer bindings are not rewritten.

Historical PIT remains UNPROVEN; historical eight-quarter coverage credit is
zero. Prospective binding confers neither historical qualification nor ranking
authorization. Other component source readiness remains unproven.

## Independent Eligibility Bridge

`RATE_PROSPECTIVE_FUNDAMENTAL_INPUT_BRIDGE_V1` requires an out-of-band trusted
verdict content hash from a cold-verified bundle. Top50 and Long require its
accepted Fundamental PASS value, plus every unchanged existing component
requirement. Short retains all its own mandatory inputs without Fundamental.
The independent contract declares the same component requirements and validates
prospective owner verdicts without importing the engineering-only V1 engine or
acceptance sandbox. Regression compares the declarations to V1, but the runtime
never creates `formal_eps_period_identity=PASS`. Missing components are NOT_EVALUATED, not
inferred ready. Input readiness is not execution authorization; scores/ranks
remain null in bridge output. No renormalization or weight redistribution.

Other component verdicts require an independent population identity pinned by
the Phase L caller. The Fundamental owner's valid-score subset must not be
inferred to be that population or used to exclude Fundamental-missing issuers
from otherwise complete Short inputs.

## Offline Operation

The new consumer CI group runs in a fresh local native Git clone with its own
index. Legacy archive mirrors remain unchanged for inherited regressions; they
must not impersonate a clean CLI execution checkout. A dirty native checkout
is still rejected before any consumer output is created.

`scripts/run_fundamental_ranking_consumer.py` requires `--binding`,
`--binding-sha256`, exact `--expected-base`/`--expected-head`, and a new external
`--output-dir`. `--verify-bundle` plus `--verdict-content-sha256` cold-rebuilds
an existing verdict in a separate process. Network and protected writes are
blocked by audit hooks. Real evidence and values stay private/local.

`--synthetic-only` explicitly selects engineering fixtures, which cannot pass
the real accepted-source pins and cannot be labeled real acceptance. Public CI
runs all 1329 current-main inherited tests plus new tests, and the existing
current-main replacement/continuity gate, on exact PR HEAD in Windows/Linux.
No existing assertion, skip rule, failure disposition or historical pin changes.

Next gate: `CONTROL_CENTER_REVIEW_THEN_PHASE_L_RERUN`. PR remains OPEN; no merge.

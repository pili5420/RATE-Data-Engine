# Dispatch V1 JSON Round Trip and Offline Code Handoff

This is candidate-only control metadata, not a financial codec or production
consumer. `provider_eps_metadata.read_metadata` preserves JSON writer int/float
types and rejects duplicate keys and nonfinite values (including exponent
overflow). Financial raw JSON still uses the unchanged Decimal reader.

Scanner restart and external controller timing audits use `read_intent` and
`validate_dispatches`: V1 digest, request/plan/market/session/domain binding,
finite non-boolean times, minimum intervals and conservative session boundaries
are checked without changing persisted evidence. Domains are never spliced.
The measurement remains CAPTURE_CALL_NOT_HTTP_WIRE_START. Old spacing remains
UNPROVEN; no new code proves old dispatch times.

The CLI cold-start worker executes the real scanner CLI in independent OS
processes, substituting only synthetic catalogue/Git authority, existing revenue
inventory and a hash-pinned mock transport. It denies socket connections. The
original 57 tests are unchanged; new persistence/handoff tests are reported
separately. Windows and Linux CI contain no real provider raw or financial data.

`scripts/handoff_provider_eps_coverage.py` accepts an existing parent (including
an already-recovered successor) and the parent's saved command JSON. It validates
all source bytes and follows sealed ancestor events to real request intents.
It does not import a transport, fabricate requests or alter the parent. A new
archive pins parent files; original ancestor archive rules remain unchanged.
Only an explicitly INCOMPLETE staging directory is written until replay passes;
the published root carries a sealed HANDOFF_READY inventory and new code binding.
Rows preserve values, dates, hashes, acquisition times, labels, unknown version
fields and decisions. Only coverage identity, provenance and revalidation time
change. Inherited requests are counted once per actual ancestral request.

New plans use DISPATCH_METADATA_JSON_ROUND_TRIP_CODE_HANDOFF, with parent plan
hash, old/new head, original universe/window/transport and explicit parser,
dispatch, metadata codec and handoff module hashes. The narrow round-trip
isolation profile compares the actual new base/head, protecting all other base
files, including the financial codec, dispatch writer, original 57 tests,
Production consumers, contracts, registry and state.

Future commands are generated from saved parent arguments, replacing only
output/base/head. They are NOT EXECUTED. Separate authorization, clean exact
checkout, readiness/lineage/source replay, no unresolved stop/unknown outcome and
single-writer conditions are required before any future network continuation.
No TTM, official EPS, Fundamental, ranking or Historical PIT claim is made.

## Wait Semantics Compatibility

The V1 writer's actual_wait_seconds measures time inside boundary(), not time
since the conservative anchor. Work before boundary() legitimately reduces that
wait, including to zero. The reader enforces the unchanged >=13 second limit on
monotonic_timestamp - previous_wait_anchor_monotonic. Actual wait must remain
finite/nonnegative and cannot exceed that total elapsed interval; it need not
independently reach 13 seconds. Digest, anchor, session and clock-domain checks
are retained. The writer, financial codec and persisted evidence are unchanged.

The reviewed c4cdbfe reader's false rejection is retained as a historical
same-bytes regression. Twelve additional tests cover real writer -> disk ->
process exit -> cold CLI reader -> original digest -> no refetch -> next stock,
for pre-boundary elapsed 0, 0.0001, 0.25, 13 and 13.25 seconds. Same-session and
new-session evidence is validated separately, including early sleep/top-up and
negative short-anchor/missing-anchor/impossible-wait fixtures. The unchanged 81
previous tests and these 12 new tests are reported separately on Windows/Linux.

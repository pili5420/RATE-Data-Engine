# RATE V11 Provider Acceptance Decision Package Builder V1

This utility deterministically packages an already-PASS independent live review
and an already-PASS provider-authority qualification into the exact decision shape
consumed by the merged provider-acceptance validator.

It is packaging only.

The builder requires an explicit external
`PROVIDER_ACCEPTANCE_AUTHORIZED` Control Center authorization input, but the
builder itself is **not** the Control Center decision. It therefore emits
`builder_disposition = NOT_A_CONTROL_CENTER_DECISION`.

The returned package includes:

- canonical live-review SHA-256;
- canonical provider-acceptance decision SHA-256;
- validator-ready decision object;
- explicit license basis;
- fixed personal/internal, non-display, no-redistribution usage scope;
- fixed zero activation/registry/dependency/credit state.

For `OWNER_ASSUMED_AUTHORIZED`, provider written confirmation must remain false.
For `PROVIDER_WRITTEN_CONFIRMED`, the written-confirmation flag must be true.

The independent Control Center validation step must still supply the expected
decision hash and expected live-review hash externally. This builder does not
create those trust roots.

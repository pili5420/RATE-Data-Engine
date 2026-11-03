# RATE V11 Intraday Activation Permit Qualification V1

This additive module validates the **future Control Center permit** that would be
required before an already-qualified provider can be connected to RATE Production.

It does not issue that permit and cannot activate Production.

## Trust model

The permit is **not self-authorizing**.

The validator requires two Control-Center-supplied expected values that are
independent of the permit body:

- `expected_control_center_decision_id`
- `expected_permit_sha256`

The permit's own `control_center_decision="PASS"` and self-computed
`permit_sha256` are insufficient. The canonical permit hash must match the
external expected permit hash exactly, and the permit decision ID must match the
external expected Control Center decision ID.

A valid future permit must also bind:

- exact current main SHA;
- the external intraday dependency and the single registry dataset that may change;
- exactly the 09:30 and 12:00 cadences;
- exact 30-symbol Production universe hash and positive integer coverage in both TWSE and TPEx;
- a PASS provider-authority qualification hash with automated non-display rights;
- a PASS payload-contract qualification hash with explicit timezone, exact
  symbol-market binding and fail-closed freshness;
- a secret reference, never a secret value;
- single-use semantics;
- fallback=false and automatic-retry=false;
- CER-081 credit=0 before successful activation.

The validator is pure. It performs zero network requests, credential reads, registry
writes, scheduler changes, Decision State/Portfolio/Ledger mutations or CER-081
updates.

Actual activation still requires a separate runtime implementation that consumes a
real Control Center-issued permit, binds credential injection to a qualified provider,
adapts the source registry, and changes the Phase2 authority/validation gates. That
future runtime must remain fail-closed if any permit binding differs.

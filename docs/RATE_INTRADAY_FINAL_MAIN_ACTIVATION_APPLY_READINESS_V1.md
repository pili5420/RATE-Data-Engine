# RATE V11 Final-Main Activation Apply Readiness V1

This gate is the final **non-mutating** review before a future explicit Control
Center activation-apply authorization.

It deliberately separates two evidence classes:

1. **historical live/provider evidence**, which must remain byte/hash bound and is
   never rewritten to a newer main SHA;
2. **fresh current-main engineering evidence**, consisting of a rebuilt activation
   delta plan and a rerun full synthetic candidate review against current repository
   preimages.

The final-main delta must use the exact current repository hashes for all seven
existing mutation paths and the same provider, license basis, endpoint and secret
identity established by the historical evidence chain.

The full synthetic candidate review must be rerun against that current main and a
new exact candidate manifest.

A PASS returns only:

`READY_FOR_CONTROL_CENTER_ACTIVATION_APPLY_AUTHORIZATION`

and keeps:

- apply_allowed=false;
- activation_execution_allowed=false;
- external_dependency_resolved=false;
- registry_activation_allowed=false;
- Production credit=0;
- CER-081 credit=0.

Single-cadence live evidence remains single-cadence; the untested cadence is not
silently promoted.

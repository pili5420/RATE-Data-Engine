# RATE V11 Live Evidence Binding V1

This gate binds one real single-live qualification review to one exact previously
reviewed activation candidate and one Control Center provider-acceptance result.

It is pure validation. It does not apply the candidate.

Required external bindings:

- full synthetic candidate review SHA-256;
- live qualification review SHA-256;
- provider acceptance result SHA-256;
- provider acceptance decision SHA-256;
- candidate manifest SHA-256;
- candidate base-main SHA;
- provider identity;
- explicit license basis;
- exact live-evidence cadence.

The gate preserves evidence scope. A 09:30 live probe proves 09:30 live evidence
only and records 12:00 as live-untested; a 12:00 probe behaves symmetrically.
Provider acceptance may cover both configured cadences, but this validator does not
inflate single-cadence live evidence into both.

A PASS returns:

- `binding_status = LIVE_EVIDENCE_BOUND`;
- `final_main_rebase_required = true`;
- `next_gate = FINAL_MAIN_REBASE_AND_ACTIVATION_APPLY_REVIEW`.

Even after a PASS:

- activation execution remains forbidden;
- the external dependency remains unresolved;
- registry activation remains forbidden;
- Production credit remains 0;
- CER-081 credit remains 0.

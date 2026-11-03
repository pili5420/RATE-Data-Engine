# RATE V11 Intraday Activation Candidate Static Review V1

This module statically reviews the **future activation candidate** before any
activation execution is authorized.

It consumes:

- a PASS dry-run Activation Delta Plan;
- an externally expected delta-plan SHA-256;
- the exact candidate contents for all seven existing mutation paths;
- the exact two new runtime files.

It validates:

- current repo preimages still match the delta plan;
- candidate path set is exact;
- dependency/source/official registry postconditions;
- Phase2 keeps authoritative admission replay;
- Phase2 no longer contains the authority-PASS forced partial-runtime raise;
- Phase2 source validation accepts all four RATE cadences rather than only
  07:30 / 19:30;
- Phase2 defines one cadence-derived intraday gate status:
  09:30 / 12:00 = PASS and 07:30 / 19:30 = NOT_APPLICABLE;
- both decision creation and transition validation bind to that same derived
  intraday status;
- hard-coded BLOCKED_EXTERNAL intraday decision-state checks are absent;
- the Phase2 builder does not acquire provider network data directly;
- 09:30 / 12:00 schedulers use the approved secret and acquisition step, remove
  public-partial runtime, and prohibit fallback/retry wiring;
- provider runtime exposes exact request/retry/fallback constants;
- Fugle runtime remains bound to `api.fugle.tw`;
- acquisition CLI does not print secrets or add fallback/retry paths.

A PASS means only
`READY_FOR_SEPARATE_ACTIVATION_IMPLEMENTATION_REVIEW`.

The validator writes no files and keeps activation/dependency/credit state unchanged.

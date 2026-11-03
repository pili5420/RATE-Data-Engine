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
- Phase2 keeps authoritative admission replay and removes the forced partial-only
  runtime after authority PASS;
- the Phase2 builder does not acquire provider network data directly;
- 09:30 / 12:00 schedulers use the approved secret and acquisition step, remove
  public-partial runtime, and prohibit fallback/retry wiring;
- provider runtime exposes exact request/retry/fallback constants;
- Fugle runtime remains bound to `api.fugle.tw`;
- acquisition CLI does not print secrets or add fallback/retry paths.

A PASS means only
`READY_FOR_SEPARATE_ACTIVATION_IMPLEMENTATION_REVIEW`.

The validator writes no files and keeps activation/dependency/credit state unchanged.

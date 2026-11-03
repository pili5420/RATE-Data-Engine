# RATE V11 Intraday Activation Delta Plan V1

This module builds a **dry-run-only** plan for the future Production activation
implementation.

It consumes:

- a PASS Activation Readiness qualification;
- a PASS Provider Acceptance qualification;
- current main SHA;
- a future Control Center activation decision ID;
- provider endpoint template;
- credential secret name.

The planner recomputes the current repository SHA-256 preimage for all seven
existing files in the approved activation mutation boundary. Caller-supplied stale
or forged preimages fail closed.

For Fugle, the endpoint must use HTTPS, host `api.fugle.tw`, and contain an exact
`{symbol}` placeholder.

The plan describes the required postconditions for:

- external dependency registry;
- source registry;
- official production source registry;
- Phase2 authority logic;
- Phase2 source builder;
- 09:30 scheduler;
- 12:00 scheduler.

## Phase2 activation blockers that must all be removed

The future candidate must close all three current hard-coded intraday blockers, not
only the first authority guard:

1. `require_intraday_authority()` may return only when the authoritative external
   dependency is PASS. The unconditional
   `PUBLIC_OFFICIAL_PARTIAL_RUNTIME_REQUIRED` raise after PASS must be removed.
2. `validate_phase2_source_bundle()` must accept all four RATE cadences and use
   `INTRADAY_REQUIRED_DATASETS` for 09:30 / 12:00 instead of restricting the
   function to 07:30 / 19:30.
3. Decision creation and transition validation must derive intraday gate state by
   cadence:
   - 09:30 / 12:00 = `PASS`;
   - 07:30 / 19:30 = `NOT_APPLICABLE`.
   Hard-coded `BLOCKED_EXTERNAL` values are forbidden after activation.

The candidate must still retain authoritative Phase2 admission replay before any
intraday consumption. Full Production acceptance, soak credit and CER-081 credit
remain separate downstream gates.

It also reserves two new runtime files:

- `src/intraday_provider_runtime.py`
- `scripts/acquire_intraday_provider_feed.py`

A PASS never applies the delta. The output always retains:

- apply_allowed=false;
- activation_execution_allowed=false;
- external_dependency_resolved=false;
- registry_activation_allowed=false;
- zero network/credential/mutation side effects;
- Production credit=0;
- CER-081 credit=0.

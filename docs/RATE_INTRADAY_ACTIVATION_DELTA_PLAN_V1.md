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

# RATE V11 Single Live Qualification Independent Review V1

This module defines the pure, provider-neutral **independent review gate** for one
already-executed Intraday live qualification.

It performs no network request, reads no credential, does not rerun a workflow,
does not select or activate a provider, does not mutate registry/scheduler state,
does not resolve the external dependency, and grants no Production/CER-081 credit.

## Required external bindings

The review package must match independently supplied values for:

- accepted engineering source SHA;
- single trigger commit SHA;
- workflow run ID;
- workflow job ID;
- provider name;
- trading date;
- cadence;
- canonical result SHA-256;
- approved Production-universe binding hash;
- exact 30-symbol symbol/market map.

## Single-use / no-retry boundary

A valid review requires:

- workflow attempt = 1;
- rerun count = 0;
- job retry count = 0;
- single-use permit consumed;
- exactly 30 provider requests;
- redirects followed = 0;
- automatic retries = 0;
- fallback = false.

## Result contract

The reviewed live result must prove:

- 30/30 coverage;
- TWSE 25 / TPEx 5;
- exact approved symbol/market mapping;
- fresh records no older than 180 seconds;
- positive price and nonnegative volume/turnover;
- token not persisted;
- no API key exposure in result/logs;
- production_eligible=false;
- registry_activation_allowed=false;
- external_dependency_resolved=false.

A PASS returns only:

`READY_FOR_CONTROL_CENTER_PROVIDER_ACCEPTANCE`

It does not itself accept the provider and never authorizes Production activation.

# RATE V11 Intraday Provider Authority Qualification V1

This package defines the **authority evidence gate** that must pass before any
provider-specific 09:30 / 12:00 runtime may be considered for Production.

It is intentionally separate from payload/schema qualification.

A provider authority manifest must prove, for both TWSE and TPEx:

- active real-time trading-information authority;
- automated non-display use is authorized;
- internal analysis use is authorized;
- the RATE internal-use boundary does not rely on redistribution rights;
- a Control-Center-approved evidence reference and SHA-256 digest exist;
- the authority validity window includes the target trading date.

The service contract must cover both markets, use real-time trading information,
provide explicit timestamp timezone semantics, and use a qualified encrypted transport.
Credentials may be referenced only by approved secret-store name; secret values and
repository secret material are forbidden.

This module performs no network request, reads no credential, chooses no vendor,
changes no source registry, and grants no Production or CER-081 credit.

A later provider-specific runtime qualification must bind this authority evidence to:
1. the actual endpoint/service;
2. the payload validator;
3. the approved 30-symbol Production universe;
4. credential injection;
5. cadence freshness;
6. Control Center registry activation.

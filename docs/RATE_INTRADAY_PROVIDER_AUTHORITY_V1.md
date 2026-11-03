# RATE V11 Intraday Provider Authority Qualification V1

This package defines the **authority evidence gate** that must pass before any
provider-specific 09:30 / 12:00 runtime may be considered for Production.

It is intentionally separate from payload/schema qualification and from the
provider-specific live runtime.

## Trust model

A provider authority manifest is **not self-authorizing**.

The validator requires a second, independent
`RATE_INTRADAY_PROVIDER_AUTHORITY_EXPECTED_BINDING_V1` supplied by the
Control Center call site. That trusted expected binding must be sourced outside
the provider manifest and fixes:

- Control Center decision ID;
- provider name and service ID;
- approved credential secret name;
- authority validity window;
- TWSE evidence reference and SHA-256;
- TPEx evidence reference and SHA-256.

The provider manifest must match those expected values exactly. A manifest that
sets `control_center_approval_status=PASS` or replaces its own evidence hashes
cannot qualify unless the independent expected binding matches.

A provider authority manifest must also prove, for both TWSE and TPEx:

- active real-time trading-information authority;
- automated non-display use is authorized;
- internal analysis use is authorized;
- the RATE internal-use boundary does not rely on redistribution rights;
- a Control-Center-approved evidence reference and SHA-256 digest exist;
- the authority validity window includes the target trading date.

The service contract must cover both markets, use real-time trading information,
provide explicit timestamp timezone semantics, and use a qualified encrypted
transport. Credentials may be referenced only by approved secret-store name;
secret values and repository secret material are forbidden.

This module performs no network request, reads no credentials, chooses no vendor,
changes no source registry, and grants no Production or CER-081 credit.

A later provider-specific runtime qualification must bind this authority evidence to:

1. the actual endpoint/service;
2. the payload validator;
3. the approved 30-symbol Production universe;
4. credential injection;
5. cadence freshness;
6. Control Center registry activation.

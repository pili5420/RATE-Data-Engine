# RATE V11 Exchange Authority Evidence Intake V1

This gate converts **private, Control-Center-approved TWSE and TPEx authority evidence**
into metadata that the existing provider-authority validator can consume.

It does not store or parse the private authorization documents themselves.

## Required evidence

Both TWSE and TPEx must independently prove:

- active authority;
- real-time trading information scope;
- automated non-display use;
- internal analysis use;
- no reliance on redistribution rights;
- a stable private evidence reference;
- SHA-256 of the approved private evidence;
- an active contract/authorization identifier;
- a validity window covering the intended trading date.

The public repository may contain only the reference, digest, scope flags, contract ID,
and validity metadata. It must not contain private evidence content, API keys, account
secrets, or raw market-data evidence.

## Output

A PASS creates the exact
`RATE_INTRADAY_PROVIDER_AUTHORITY_EXPECTED_BINDING_V1` structure required by
`src/intraday_provider_authority.py`.

A PASS here still grants:

- Production activation: **NO**
- external dependency resolution: **NO**
- CER-081 credit: **0**

The next gate is the existing
`RATE_INTRADAY_PROVIDER_AUTHORITY_QUALIFICATION_V1`.

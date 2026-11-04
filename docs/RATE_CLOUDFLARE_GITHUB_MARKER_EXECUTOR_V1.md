# RATE V11 Cloudflare GitHub Marker Executor V1

This layer implements the marker execution state machine while CI remains synthetic-only.

It validates the exact #144 authorization qualification, then performs the bounded
marker adapter sequence: preflight GET, one create attempt, exact GET readback.
Ambiguous create is resolved by readback with zero create retry. Pre-existing marker
fails before any Cloudflare request.

No real GitHub transport is accepted in CI and no real tag is created.

The executor derives the marker only from
`cloudflare_real_qualification_authorization_sha256`. The separate
`cloudflare_authorization_qualification_sha256` remains an object-integrity trust
root and is never used to derive the ref.

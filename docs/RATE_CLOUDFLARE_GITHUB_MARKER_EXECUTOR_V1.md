# RATE V11 Cloudflare GitHub Marker Executor V1

This layer implements the marker execution state machine while CI remains synthetic-only.

It validates the exact #144 authorization qualification, then performs the bounded
marker adapter sequence: preflight GET, one create attempt, exact GET readback.
Ambiguous create is resolved by readback with zero create retry. Pre-existing marker
fails before any Cloudflare request.

No real GitHub transport is accepted in CI and no real tag is created.
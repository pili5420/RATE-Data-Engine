# RATE V11 Cloudflare D1 Real Qualification Authorization V1

This gate validates one explicit Control Center authorization for a future single-use
Cloudflare Workers + D1 real-provider qualification.

It binds the exact current main, qualification-plan review SHA-256, deployment
scaffold SHA-256, Node Worker review SHA-256 and Control Center decision ID.

The authorization cannot expand any resource, administrative operation, runtime probe
or cleanup budget from the accepted plan. The administrative budget includes exactly
one account Workers-subdomain lookup used to construct the workers.dev qualification
URL and one Worker-script subdomain readiness lookup. No subdomain setting mutation
is authorized. It remains single-use, unconsumed,
no-retry and no-fallback.

Cloudflare API token, account ID and Worker bearer token are referenced only by their
GitHub Actions secret/variable names. No credential value is present.

A PASS is authorization qualification only. This validator does not create resources
or execute Cloudflare requests. The next gate is a separate one-shot real
qualification executor.


The authorization also binds one durable single-use consumption marker: one
lightweight Git tag ref create/readback before the first Cloudflare request. Ref
update/delete and marker reuse are not authorized.

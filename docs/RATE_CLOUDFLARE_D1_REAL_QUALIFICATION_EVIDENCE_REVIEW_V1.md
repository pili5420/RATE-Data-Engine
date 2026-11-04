# RATE V11 Cloudflare Real Qualification Evidence & Cleanup Review V1

This pure review gate defines the evidence package required after a future real
Cloudflare Workers + D1 qualification run.

Acceptance requires:
- exact workflow run/job identity, first attempt only, no rerun;
- exact Cloudflare authorization and current-main bindings;
- consumed/read-back Git marker before Cloudflare traffic;
- exactly 17 Cloudflare requests: 11 admin/cleanup and 6 runtime;
- exact runtime statuses 401 / 404 / 201 / 200 / 409 / 405;
- exact temporary D1/Worker identities derived from the authorization hash;
- D1 read replication disabled;
- Worker/script/schema SHA evidence;
- mandatory Worker and D1 cleanup, one attempt each, zero retry/failure/residual;
- all ten required result-evidence objects with immutable references and SHA-256;
- an externally bound evidence-manifest SHA-256;
- no credential values in the evidence package.

A PASS returns only READY_FOR_CONTROL_CENTER_CLOUDFLARE_PROVIDER_ACCEPTANCE.
It does not itself qualify or activate the provider.

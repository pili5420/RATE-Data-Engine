# RATE V11 Synthetic Cloudflare Qualification Executor Rehearsal V1

This layer rehearses the entire future one-shot Cloudflare Workers + D1 provider
qualification against an in-memory backend only.

The sequence consumes the single-use authorization before the first synthetic
Cloudflare mutation, then executes the exact eight administrative operations (including Workers-subdomain discovery) and six
runtime probes from the approved plan.

All failures after consumption are non-retryable. The rehearsal performs at most one
cleanup attempt for each created Worker/D1 resource. If cleanup leaves any residual
resource, the disposition is BLOCKED_RESIDUAL_RESOURCE.

A successful rehearsal proves sequencing and cleanup semantics only. It creates no
real Cloudflare resource, performs no real request, reads no credential and does not
qualify the real provider.

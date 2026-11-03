# RATE V11 Cloudflare D1 Real Provider Qualification Plan V1

This layer fixes the exact boundary for one later, separately authorized real
Cloudflare provider qualification.

The qualification uses temporary resources only:

- one D1 database with read replication disabled;
- one Worker script;
- one Worker secret;
- zero custom routes/domains;
- workers.dev endpoint only.

The Cloudflare API token must be stored as a GitHub Actions secret and limited to
D1 Write and Workers Scripts Write. The account ID is a GitHub Actions variable.
No secret value is embedded in the plan or repository.

The administrative budget includes exactly one account Workers-subdomain lookup
to derive the qualification-only workers.dev endpoint from Cloudflare rather than
storing the account subdomain in GitHub, plus one Worker-script subdomain readiness
lookup. The qualification fails closed if that script is not enabled on workers.dev;
it does not mutate subdomain settings.

The runtime probe budget is exactly one each of unauthorized GET, missing GET,
create POST, readback GET, duplicate POST and unsupported method. Automatic retry
and fallback are forbidden.

Qualification credit requires mandatory cleanup of both Worker and D1. Any residual
resource after the one allowed cleanup attempt yields BLOCKED_RESIDUAL_RESOURCE.

This PR is plan-only and performs zero Cloudflare requests, reads zero credentials
and creates zero resources.


## Durable single-use consumption marker

Before the first Cloudflare request, the future executor must atomically create and
read back exactly one lightweight Git tag ref under
`refs/tags/rate-v11-qualification-consumed/cloudflare-d1-<first16hex>`, where the
suffix is the first 16 hexadecimal characters of the authorization qualification
SHA-256. The ref targets the exact current main bound by the authorization. Ref update and deletion are forbidden.
A duplicate/pre-existing marker blocks qualification before any Cloudflare request.

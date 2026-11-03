# RATE V11 Cloudflare HTTP Request-Shape Rehearsal V1

This layer builds the exact future Cloudflare REST and workers.dev request sequence,
but executes it only against an in-memory synthetic transport.

The rehearsal covers:

- D1 database create with read_replication.mode=disabled;
- Worker module multipart upload with main_module=worker.mjs and D1 binding DB;
- Worker secret PUT;
- D1 schema query;
- D1 metadata, Worker script, secret metadata, account subdomain and Worker-script
  subdomain readiness GETs;
- six workers.dev runtime probes;
- Worker and D1 cleanup DELETEs.

The exact request count is 17: 9 administrative reads/writes, 6 runtime probes and
2 cleanup calls. No retry or fallback is allowed.

Cloudflare admin token headers are restricted to api.cloudflare.com. The Worker
bearer secret is never embedded in the script upload and never used as the Cloudflare
admin Authorization header.

No real HTTP transport is accepted by this engineering module.

# RATE V11 Cloudflare HTTPS Transport Integration Rehearsal V1

This layer reuses the accepted 17-request Cloudflare request-shape rehearsal unchanged,
but routes every request through the bounded Cloudflare HTTPS transport.

HTTPSConnection is fully replaced with an in-memory fake Cloudflare server. Therefore
the integration exercises the actual transport validation/TLS/connection lifecycle
without any real network access.

A PASS requires:

- all 17 request shapes still pass;
- 11 api.cloudflare.com admin/cleanup requests;
- 6 workers.dev runtime requests;
- exactly 17 bounded transport requests;
- exactly 17 HTTPS connections, all closed;
- hostname verification enabled on every connection;
- zero retry, redirect follow and fallback;
- zero real network/Cloudflare requests.

This is the final offline integration gate before any separately authorized real
Cloudflare qualification execution.

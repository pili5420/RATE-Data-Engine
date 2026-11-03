# RATE V11 Cloudflare D1 Node Worker Runtime Review V1

This layer executes the actual generated worker.mjs under Node.js with a fake D1
binding. It therefore validates JavaScript runtime behavior rather than only a Python
model or static source scan.

The harness proves:

- wrong bearer token -> 401;
- invalid execution-ID route -> 404;
- unsupported method -> 405;
- first POST -> 201 CREATED_AND_READBACK_VERIFIED;
- GET -> exact stored receipt;
- duplicate POST -> 409 ALREADY_EXISTS;
- D1 failure before insert -> 503 D1_CREATE_FAILED;
- exactly three insert attempts for the three POST calls, with zero hidden retry;
- failed insert creates no record.

The Worker source is imported directly from the generated scaffold. The harness has
no outbound network capability and uses no Cloudflare resource or real credential.

A PASS still does not qualify the real Cloudflare provider. The next gate is a
separately authorized real-provider qualification.

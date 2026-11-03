# RATE V11 Cloudflare Bounded HTTPS Transport V1

This module is the production-shaped HTTPS transport intended for a future explicitly
authorized Cloudflare qualification executor.

Security properties:

- HTTPS only;
- Cloudflare admin credential scope only to api.cloudflare.com;
- Worker credential scope only to exact qualification Worker hosts matching
  rate-v11-qual-<12 hex>.<account-subdomain>.workers.dev;
- no userinfo, custom port, query, fragment, path traversal or percent-encoded path;
- TLS uses Python's default trust store with hostname checking and CERT_REQUIRED;
- one connection and one request per call;
- no redirect following;
- no automatic retry or fallback;
- bounded request and response bytes;
- connection closed in a finally boundary;
- transport exceptions do not include headers, bodies or credential values.

CI replaces HTTPSConnection with a fake connection class. This PR performs zero real
network or Cloudflare request.

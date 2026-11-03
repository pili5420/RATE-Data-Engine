# RATE V11 Cloudflare Worker + D1 Deployment Scaffold V1

This layer builds a non-deploying three-file scaffold for the selected Cloudflare
Workers + D1 durable receipt-store candidate:

- worker.mjs
- schema.sql
- wrangler.jsonc

The Worker exposes only exact execution-ID GET and POST routes. It has no arbitrary
SQL endpoint and no update/delete/list route. POST performs one INSERT. A database
primary-key conflict is an explicit duplicate and returns 409; other database errors
return 503. The Worker never retries INSERT.

Transport ambiguity is handled by the external client adapter: if the HTTP outcome is
unknown after POST, the client performs one GET of the same execution ID and never
retries POST.

The D1 schema uses execution_id as PRIMARY KEY and includes fail-closed UPDATE and
DELETE guards. The Wrangler configuration contains only placeholder database
identity and never contains the Worker bearer secret.

This is still design engineering only. No Cloudflare deployment, account/database
identifier, credential, or network request is used. Real D1 schema compatibility and
Worker runtime semantics remain separate review gates.

# RATE V11 Cloudflare Workers + D1 Authority Store Candidate V1

Selected zero-cost candidate for the future durable real-Git execution receipt:

- Cloudflare Workers Free;
- Cloudflare D1 Free;
- an authenticated Worker proxy;
- D1 accessed only through a Worker binding;
- D1 read replication disabled;
- execution_id as the receipt-table primary key;
- create/read routes only;
- no arbitrary SQL, update, delete or list route exposed to the executor.

The Worker performs one create attempt using a plain INSERT protected by the primary
key. Duplicate execution IDs fail. An ambiguous create outcome is resolved by reading
the same execution ID and never by retrying create.

D1 administrative REST access is not exposed to the RATE executor. The client only
holds the Worker bearer secret through GitHub Actions secret injection.

Current official provider references used for candidate selection include Workers
Free limits, D1 Free pricing, D1 primary/read-replication semantics, D1 replication
configuration, and D1 SQLite query semantics.

This is design qualification only. No Cloudflare resource, credential or request is
used. Real provider qualification and schema/Worker deployment evidence remain future
gates.

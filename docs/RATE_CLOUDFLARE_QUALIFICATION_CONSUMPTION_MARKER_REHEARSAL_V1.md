# RATE V11 Cloudflare Qualification Durable Consumption Marker Rehearsal V1

This layer rehearses the write-once Git-ref marker required to consume a Cloudflare
qualification authorization before the first Cloudflare request.

The deterministic marker is:

refs/tags/rate-v11-qualification-consumed/cloudflare-d1-<first16hex>

where <first16hex> is derived from the authorization-qualification SHA-256. The marker
targets the exact current main.

The synthetic backend proves atomic create-if-absent semantics, exact readback,
pre-existing marker fail-closed behavior, conflicting-target rejection, and ambiguous
create recovery by readback without create retry. Ref update and delete counts remain
zero.

No real Git ref or Cloudflare request is created by this rehearsal.

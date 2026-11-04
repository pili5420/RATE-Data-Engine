# RATE V11 GitHub Ref Marker Adapter Qualification V1

This layer qualifies the exact GitHub ref API semantics required by the Cloudflare
single-use qualification consumption marker.

Allowed request shapes are limited to:
- POST /repos/pili5420/RATE-Data-Engine/git/refs
- GET the exact marker ref

The marker is a lightweight tag:
refs/tags/rate-v11-qualification-consumed/cloudflare-d1-<authorization hash prefix>

The adapter requires preflight read, single create, exact readback, no update/delete,
and no create retry after an ambiguous create outcome. A pre-existing marker is
treated as already consumed before Cloudflare traffic.

CI uses only a synthetic GitHub transport. No real GitHub ref is created.

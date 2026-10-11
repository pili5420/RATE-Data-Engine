# Prospective Known Failure Recovery V1

This opt-in offline reader distinguishes successful acquisitions, terminal HTTP
failures with trusted evidence, and truly unknown requests. It is not an
acquisition command, provider activation, full-soak acceptance, or First Refresh.

The original store and its singleton STOP remain read-only. An externally pinned
binding freezes its original files, original execution checkout and producer
hash, authority, successful head, failed intent, raw/receipt, pre-opener start,
dispatch, original traceback, STOP and pre-failure checkpoint. The original
producer reconstructs successful records without changing their identities.

Recovery writes only to a separate external overlay. Each failure has an immutable
`failures/<intent_id>/FAILURE.json`; each resolution has an immutable per-intent
slot plus `objects/<sha256>.json`. Explicit trusted checkpoint hashes are required
for cold replay. Duplicate resolution creation is rejected, not treated as retry.

A legacy STOP is covered only by a resolution of that exact intent. Every other
unresolved intent still blocks. A known HTTP outcome requires source, endpoint,
authority, configuration, request identity, exact bytes and chronology validation;
an exception string or self-asserted status is insufficient. Observation ordering
is local evidence ordering, not provider revision history or historical PIT.

Per-intent storage supports multiple independent failure records without replacing
the first STOP. This reader does not make the legacy acquisition writer or its
singleton STOP safe for new live requests: that writer remains unchanged. Any
later acquisition requires separate Control Center authorization and a versioned
execution/store binding, a new intent ID and per-intent failure capture integration.
No recovery command dispatches transport or clears an old gate. The original
failed intent can never be used again.

Public CI is synthetic only. Real failure bytes, receipts and finance rows remain
in local evidence storage. Production, ranking, scheduler and Portfolio owners
have no dependency on this opt-in module. Historical PIT stays UNPROVEN and
original eight-quarter coverage credit remains zero.

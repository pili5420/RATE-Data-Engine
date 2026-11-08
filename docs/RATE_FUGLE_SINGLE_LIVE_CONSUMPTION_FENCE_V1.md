# RATE V11 Fugle Single-Live Consumption Fence V1

This gate proves the crash-safe single-use ordering required before a real Fugle
qualification can touch credentials or the provider.

The required sequence is:

1. validate the authorization review;
2. check that no existing receipt exists;
3. obtain a successful exclusive-create acknowledgement in this invocation;
4. read the receipt back and verify exact identity;
5. only then permit credential access;
6. only then permit the exact 30-request qualification.

An ambiguous write grants no executor ownership. Lost acknowledgement, a create
conflict and unknown state fail closed without retry. A readback of the same main
SHA cannot establish who created the receipt. A persisted receipt after a lost ACK
remains consumed and blocks reentry. Only the acknowledged creator may continue
after matching readback. The synthetic store uses an atomic lock for this decision.

CI uses a synthetic write-once store and synthetic executor only. It performs no
credential read and no real provider request.

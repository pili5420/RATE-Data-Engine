# RATE V11 Synthetic Git Transaction Executor Rehearsal V1

This layer rehearses the future single-use activation Git transaction against an
in-memory synthetic backend only.

It executes the intended sequence:

1. validate current main and exact candidate;
2. consume the single-use transaction token;
3. create exactly 9 synthetic Git blobs;
4. create a synthetic tree based on the current main tree;
5. create a synthetic commit with current main as the only parent;
6. create the dedicated activation branch ref **last**.

The main ref is never changed.

Any failure after token consumption is intentionally non-retryable. Synthetic
unreachable Git objects may exist after a simulated failure, but no activation
branch ref is created and main remains unchanged.

This module rejects subclass/real backends and creates zero real Git objects,
branches, pull requests or repository writes.

# RATE V11 Real Git Data HTTP Executor Rehearsal V1

Fully offline rehearsal of the GitHub Git-Data request sequence for one activation
transaction.

Sequence: verify main ref; fetch the exact main commit to obtain its immutable tree;
verify target branch absence; create exactly 9 blobs, one tree using that base tree,
one commit parented by exact main, one activation branch ref, then read the branch
back.

Blob/tree/commit failures never create a branch and are never retried. An ambiguous
branch-ref create is resolved only by reading the exact branch ref; the create POST is
not retried.

CI uses a synthetic HTTP transport. No real GitHub object or ref is created.
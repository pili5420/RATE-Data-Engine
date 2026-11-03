# RATE V11 Activation Apply Transaction Plan V1

This layer converts one already-qualified single-use activation authorization and
one exact 9-file candidate into a deterministic **non-mutating Git transaction
plan**.

The plan binds:

- exact base main SHA;
- exact candidate manifest SHA-256;
- authorization qualification SHA-256;
- Control Center decision ID;
- provider identity;
- current repository preimage SHA-256 for the 7 existing files;
- confirmed absence of the 2 new runtime files;
- per-file content SHA-256;
- per-file Git blob SHA-1;
- exact CREATE_NEW vs REPLACE_EXISTING operation.

The plan proposes a dedicated activation branch but explicitly forbids direct main
updates and merge.

It does not create Git blobs, trees, commits, branches or pull requests.

Any main/preimage drift requires a new transaction plan.

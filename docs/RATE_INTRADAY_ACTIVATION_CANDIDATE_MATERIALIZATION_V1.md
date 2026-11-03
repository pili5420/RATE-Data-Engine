# RATE V11 Activation Candidate Isolated Materialization Review V1

This layer proves that the already-reviewed in-memory activation candidate can be
materialized byte-exactly into an **external isolated workspace** and then re-read
without semantic drift.

It is not an activation apply step.

The materializer requires:

- exact 9-file candidate allowlist;
- externally supplied candidate-manifest SHA-256;
- an existing empty workspace outside the repository;
- no symlink workspace root;
- relative non-traversing paths only;
- exclusive create;
- byte-exact and SHA-256 readback.

After materialization, the reviewer reconstructs the candidate map from disk and
reruns:

1. activation candidate static review;
2. Python/YAML/JSON syntax and AST review;
3. fake-HTTPS runtime semantic review with authoritative Phase2 intraday admission.

Any file tamper after materialization invalidates the external manifest hash.

This layer permits writes only to the isolated review workspace. Repository writes,
real provider requests, credential access, activation, registry/scheduler mutation,
Production credit and CER-081 credit remain zero.

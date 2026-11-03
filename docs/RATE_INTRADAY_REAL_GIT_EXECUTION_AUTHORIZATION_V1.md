# RATE V11 Real Git Transaction Execution Authorization V1

This gate validates one future explicit Control Center authorization to execute the
already-reviewed activation transaction against the real GitHub repository.

It does not execute Git operations.

The authorization is bound to the exact:

- base main SHA;
- transaction plan SHA-256;
- synthetic rehearsal SHA-256;
- candidate manifest SHA-256;
- provider identity;
- dedicated activation branch;
- Control Center decision ID.

The exact real Git operation budget is:

- 9 blob creations;
- 1 tree creation;
- 1 commit creation;
- 1 dedicated branch-ref creation;
- 1 Draft pull-request creation;
- 0 main-ref updates;
- 0 merges.

The transaction remains single-use, no-retry and no-fallback. No additional live
provider request, secret value, Production credit or CER-081 credit is authorized.

A PASS means only authorization validity. A separate real Git transaction executor
must still enforce the operation budget and stop before merge.

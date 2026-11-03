# RATE V11 Real Git Transaction Execution Authorization Qualification V1

This gate validates one explicit Control Center authorization for the future
real Git transaction executor.

It is narrower than the earlier activation-apply authorization. The authorization
must bind one exact current main SHA, transaction-plan SHA-256, synthetic
rehearsal-result SHA-256, candidate-manifest SHA-256, provider identity, dedicated
activation branch, and Control Center decision ID.

The allowed real Git object budget is exactly 9 blobs, 1 tree, 1 commit, and
1 branch ref created last.

Only CREATE_BLOBS, CREATE_TREE, CREATE_COMMIT, and CREATE_BRANCH_REF are allowed.
Direct main update, pull-request creation, merge, and branch deletion remain
forbidden.

A PASS means authorization qualification only. This validator creates no Git
objects or refs and does not consume the single-use authorization.

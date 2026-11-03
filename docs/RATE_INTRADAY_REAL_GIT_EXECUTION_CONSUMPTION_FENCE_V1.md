# RATE V11 Real Git Execution Durable Consumption Fence V1

This engineering layer defines the single-use durability boundary required before
a future real Git executor is allowed to create its first Git object.

The fence validates an exact real-execution authorization qualification and then
writes one immutable receipt with state:

CONSUMED_BEFORE_GIT_MUTATION

The receipt binds the execution ID, authorization-qualification SHA-256, exact base
main, target branch, transaction-plan SHA-256, candidate-manifest SHA-256 and
provider identity.

Required ordering:

1. all authorization/main/branch bindings pass;
2. verify no prior receipt exists;
3. persist the write-once consumption receipt;
4. read back and verify the receipt;
5. only then may a separate future executor create its first Git blob.

A process restart or failure after consumption remains non-retryable because the
receipt survives independently of executor memory.

CI uses only a synthetic write-once receipt store. No real authority store, Git
operation, repository write, provider request, activation or Production credit is
performed here.

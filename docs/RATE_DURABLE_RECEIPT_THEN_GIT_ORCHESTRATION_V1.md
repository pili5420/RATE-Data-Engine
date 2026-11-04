# RATE V11 Durable Receipt → Synthetic Git Transaction Orchestration V1

This layer proves the fail-closed ordering required by a future real activation
transaction.

The complete non-mutating preflight validates the accepted authority-store readiness,
real-Git authorization, transaction plan, candidate manifest, every planned file
hash/blob identity, current main and target-branch absence.

Only after all preflight checks pass does it persist and read back the write-once
consumption receipt in state CONSUMED_BEFORE_GIT_MUTATION. Only then may the synthetic
Git transaction begin.

If receipt persistence fails, Git is never called. If Git fails after receipt
consumption, the receipt remains durable and any process-style reentry is rejected
before new Git calls.

CI uses only SyntheticWriteOnceReceiptStore and SyntheticGitBackend. No real authority
store, Git object/ref/PR, repository write or provider request is performed.


## Single-use trust-root precedence

The durable receipt store is authoritative across process boundaries. On reentry:

1. if the execution receipt already exists, the attempt fails immediately as already
   consumed before any synthetic/backend state is interpreted;
2. only when no durable receipt exists may ephemeral Git-backend consumed state be
   examined;
3. if ephemeral state claims consumed while the durable receipt is absent, the state
   is inconsistent and fails before any receipt write or Git mutation.

# RATE V11 Real Authority Store Adapter Qualification V1

This layer defines the semantic contract for the external durable store that will
hold the real-Git execution consumption receipt.

Required store properties:

- external persistence;
- atomic create-if-absent by exact execution ID;
- strong read-after-write;
- no overwrite;
- no delete;
- no unbounded listing;
- TLS with server identity verification;
- secret-reference credentials only;
- exact receipt-key scope.

Ambiguous create handling is fail-closed: if the create may have succeeded but the
client receives an ambiguous transport outcome, the caller must not retry create.
It performs one read of the same execution ID. An exact persisted receipt confirms
consumption; absence remains unresolved and cannot be converted into a retry.

CI uses only a synthetic adapter. No real authority store, network transport, Git
operation, provider request, repository write or Production mutation occurs.

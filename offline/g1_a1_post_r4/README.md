# G1-A1 Post-R4 synthetic interfaces

These modules are offline simulations and static contracts. `SyntheticTrust` uses
test-only HMAC keys. `SyntheticMemoryAnchor` is a process-local simulation; it is
not independently immutable custody. No operational authority, host probe,
credential access, network request, deletion, or retention transition is exposed.

## Traceability

| Workstream | Source | Evidence |
| --- | --- | --- |
| A Authority adapter | `authority.py` | Exact permit/source/workflow/run/attempt/scope binding; one-use ledger ACK; tests for forgery, expiry, revocation, replay, concurrency, lost ACK, partial failure |
| B Custody and receipt | `custody.py` | Receipt/package binding; references; backup inventory; simulated create-once ACK and readback; retention anchor from accepted receipt only |
| C Negative harness | `test_post_r4.py` | Executed synthetic positive and negative tests; prior R2 regression suite runs alongside |
| D Static host contracts | `host_contracts.py` | Identity, OS capability, credential isolation, authority/custody binding, evidence and manual fail-closed recovery; operational gate permanently blocked |

The prior R2 simulator remains the source of review acceptance, deletion
authorization, and the 30-day retention state machine. This batch does not alter
those controls.

Run from repository root:

```text
python -B -m unittest -v offline.g1_a1_post_r4.test_post_r4
```

For the accepted R2 suite, run `python -B -m unittest -v test_simulator` in
`offline/model_s_s2_r2`, with `MODEL_S_S2_TEST_TMP` pointing to a writable
temporary directory outside the tracked repository.

Remaining operational blockers: independent natural-person Verifier unassigned;
C11 authenticated adoption incomplete; custody destination unbound; immutable
external anchor, host identity, credential isolation, backup inventory, and
operational authority remain unimplemented and unqualified.

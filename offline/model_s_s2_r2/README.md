# RATE V11 Model S S2 offline simulator

This directory is isolated engineering source for synthetic tests. It is not imported by Production, a workflow, a custody service, or any adopted contract. It has no network client, host inventory code, signing permit, file-deletion operation, or operational key loader. The only persistent write is a caller-supplied `ledger.sqlite` inside a `SYNTHETIC_*` scratch directory. Tests use `MODEL_S_S2_TEST_TMP` to place that scratch directory outside the tracked repository.

The five proposed amendments are bound by [`SOURCE_BINDING.json`](SOURCE_BINDING.json). Their approval is for the **offline baseline only**. The source ZIP and independent verification ZIP must be checked separately; their bytes are not copied or adopted into this repository. Frozen C03 and Model C stay unchanged.

## Run offline tests

From this directory, with Python 3.12 or later:

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
$env:MODEL_S_S2_TEST_TMP='C:\path\to\writable\synthetic-test-root'
python -m unittest -v test_simulator
```

The tests create only `SYNTHETIC_*` scratch directories and clean them after verifying the resolved cleanup path. No credentials or real signing keys are used.

## Boundaries

- `SyntheticTrust` uses HMAC-SHA256 with literal synthetic test keys. This validates a cryptographic authentication interface and forged-message rejection. It is **not** an asymmetric digital-signature implementation or evidence of operational key custody. An operational Receipt Authority needs a separately approved key scheme, protected trust root, revocation source and independent qualification.
- `ReplayLedger` uses SQLite unique claims, explicit transaction boundaries and an internal hash chain. A durable claim is committed before receipt processing. An uncertain result burns the token. Lost ACK does not authorize readback-based continuation. The hash chain is an **immutable-anchor simulation**, not independent immutable custody; a privileged DB editor could rewrite it.
- `review_acceptance` returns `TECHNICAL_VALIDATION_ONLY`. It never asserts independent natural-person review or Owner governance adoption.
- `RetentionMachine` starts a **simulated** 30-calendar-day UTC interval only from a receipt whose exact binding and anchor are found in the synthetic ledger. It does not start the operational C10 clock.
- Deletion authorization and confirmation are signed synthetic envelopes with unique ledger claims. They never delete a file. A held, unknown, expired, duplicated or mismatched action is blocked.
- Every `PASS` is limited to the local synthetic model. G1, B7, C11 adoption, custody destination, signing permit, Production and CER-081 remain blocked or uncredited.

## Review focus

Recompute source ZIP, internal manifest, five candidate hashes and verification ZIP independently. Inspect `simulator.py` for claim/commit order, signature and exact binding checks, UTC boundary handling, no-fallback results, and the absence of operational imports. Run every test without skips, inspect the per-test log and failure-injection results, and check the exact branch Head and diff before any separate decision.

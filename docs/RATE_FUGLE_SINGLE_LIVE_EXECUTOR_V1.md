# RATE V11 Fugle Single-Live Executor V1

This module composes the already-qualified pieces into one production-shaped
single-live execution path:

1. validate the fresh authorization review;
2. preflight the exact GitHub consumption marker;
3. create the marker once;
4. read the same marker back;
5. only after readback, use `FUGLE_API_KEY`;
6. execute the existing exact 30-request Fugle qualification;
7. return evidence for the independent live-review gate.

If the consumption marker already exists, the provider is not contacted.

If marker creation is ambiguous, the adapter performs readback only; it never retries
the create.

If the provider later fails after the marker is durably consumed, the authorization
remains consumed. There is no automatic retry and no fallback.

CI patches GitHub HTTPS and injects a fake Fugle connection factory. Therefore CI
performs zero real GitHub or Fugle requests and uses no real credentials.

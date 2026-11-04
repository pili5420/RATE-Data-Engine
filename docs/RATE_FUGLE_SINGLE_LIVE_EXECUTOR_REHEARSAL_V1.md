# RATE V11 Fugle Single-Live Executor Rehearsal V1

This is an **offline execution-plan rehearsal** for the future authorized Fugle
single-live executor.

It accepts only a PASS result from the fresh authorization validator and verifies:

- exact main SHA and authorization SHA-256;
- single-use permit is still unconsumed;
- request budget is exactly 30;
- cadence is exactly 09:30 or 12:00;
- retry/fallback/redirect remain forbidden;
- credential is referenced only as `FUGLE_API_KEY`;
- output remains a new JSON basename under the existing protected diagnostic root.

The rehearsal emits the exact command shape for
`scripts/run_fugle_intraday_qualification.py` but performs **zero network requests,
zero credential reads, zero file writes, and does not consume the authorization**.

The real executor must durably create and read back the single-use consumption marker
before reading the credential or issuing the first provider request.

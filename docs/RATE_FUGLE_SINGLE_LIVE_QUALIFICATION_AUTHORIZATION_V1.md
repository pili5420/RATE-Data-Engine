# RATE V11 Fugle Single-Live Qualification Authorization V1

This gate validates a future **fresh Control Center authorization** for exactly one
Fugle live qualification.

A valid authorization is bound to:

- exact current `main` SHA;
- exact readiness-package SHA-256;
- Control Center decision ID;
- Fugle as provider;
- exactly one cadence: 09:30 or 12:00;
- maximum 30 requests;
- single-use and unconsumed state;
- no retry, no fallback, no redirect;
- GitHub Actions secret `FUGLE_API_KEY`;
- no embedded credential value.

The validator itself performs no network request and cannot consume the permit.
A PASS only means the authorization object is structurally valid for the separate
executor.

Any execution attempt must create durable single-use evidence before the first
provider request and must remain bound to the independent live-review gate.

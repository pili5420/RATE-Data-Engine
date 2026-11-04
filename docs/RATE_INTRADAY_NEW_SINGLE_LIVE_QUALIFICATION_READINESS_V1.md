# RATE V11 New Single-Live Qualification Readiness V1

This is the final engineering gate before the Control Center may consider issuing a
**fresh** single-use live qualification authorization.

A PASS requires all of the following:

1. Fugle provider use is bound to `PROVIDER_WRITTEN_CONFIRMED`.
2. TWSE and TPEx authority evidence intake is PASS.
3. The existing provider-authority qualification is PASS.
4. The provider-authority binding hash matches the exchange-intake expected binding.
5. The previously consumed single-use permit is explicitly non-reusable.

A PASS returns only:

`READY_FOR_CONTROL_CENTER_NEW_SINGLE_LIVE_AUTHORIZATION`

It does **not** issue the permit, perform a provider request, read a credential,
activate the registry, resolve the external dependency, or grant Production/CER-081
credit.

After a separate Control Center authorization, one live qualification may execute
under its own single-use/no-retry/no-fallback contract. The resulting evidence must
then pass the existing independent live-review gate before provider acceptance.

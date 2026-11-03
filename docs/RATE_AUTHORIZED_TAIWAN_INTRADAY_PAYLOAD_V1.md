# RATE Authorized Taiwan Intraday Payload Qualification V1

This additive mainline engineering layer validates the shape of an already-authorized
09:30 / 12:00 intraday payload without selecting or contacting a provider.

It requires exact 30-symbol approved-universe coverage across both TWSE and TPEx,
explicit binding to a validation-PASS RATE Production source bundle (snapshot ID,
source-bundle SHA256 and canonical universe SHA256), rejection of non-canonical or
normalization-colliding expected symbols, explicit timezone-bearing timestamps,
same-trading-date binding, bounded freshness, finite price/volume/turnover values,
exact symbol-market binding, no duplicates, an automated-production-use license
scope whose markets field is a JSON array of non-empty market strings covering both
TWSE and TPEx, and fallback=false.

Provider payloads may contain additional symbols; those are `ALLOWED_NOT_SELECTED`.
Missing approved symbols, wrong markets, expected-universe source/hash mismatch,
normalization collisions, malformed license market structures, stale/future data,
naive timestamps, missing license authority or any fallback fail closed.

This package performs zero network requests and accesses zero credentials. A PASS
means only that the payload contract is technically qualifiable. It does not change
the Production source registry, does not resolve
`EXTERNAL_AUTHORIZED_INTRADAY_FEED_DEPENDENCY`, and grants no scheduler, Decision
State, Portfolio, Ledger, CER-081 or Production acceptance credit.

A later provider-specific qualification and Control Center activation must bind the
actual contract/license, endpoint, credential handling, timestamp semantics and
registry entry before this validator can participate in Production.

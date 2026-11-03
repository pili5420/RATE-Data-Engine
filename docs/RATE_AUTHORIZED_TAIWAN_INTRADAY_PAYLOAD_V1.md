# RATE Authorized Taiwan Intraday Payload Qualification V1

This additive mainline engineering layer validates the shape of an already-authorized
09:30 / 12:00 intraday payload without selecting or contacting a provider.

## Authoritative universe trust chain

The caller does **not** establish the approved 30-symbol universe.

The validator independently binds the expected universe through the repository's
Production authority chain:

1. `config/RATE_PRODUCTION_UNIVERSE_CONTRACT_V1.json`
   - artifact = `RATE_PRODUCTION_UNIVERSE_CONTRACT`
   - purpose = `PRODUCTION_SOURCE_ACQUISITION_BINDING`
   - validation = PASS
   - exact approved universe = 30 symbols
2. `artifacts/RATE_PRODUCTION_SOURCE_BUNDLE_LATEST.json`
   - validation = PASS
   - resolves one immutable Production bundle and Production snapshot ID
3. The immutable `RATE_PRODUCTION_SOURCE_BUNDLE.json`
   - validation/source/bundle-validation = PASS
   - canonical bundle SHA256 must equal LATEST.source_bundle_hash
4. The bundle's `universe_binding`
   - production_authoritative = true
   - binding_mode = `AUTHORITATIVE_CONTRACT_EXACT_30`
   - expected_universe exactly equals the Production universe contract
   - contract SHA256 is recomputed from the contract
   - universe_binding_hash is recomputed from the approved universe + contract SHA256
5. The bundle's 30 records provide the authoritative symbol→listed_market binding.
   Their ordered symbol list must exactly equal the approved contract universe.

Caller-supplied `expected_universe` and binding metadata are assertion-only. They must
exactly match this independently derived trust chain. Replacing the caller's 30 symbols,
snapshot, bundle hash, universe hash, contract hash and binding hash together does not
change the authority and fails closed.

## Payload gates

The validator also requires both TWSE and TPEx, explicit timezone-bearing timestamps,
same-trading-date binding, bounded freshness, finite price/volume/turnover values,
exact symbol-market binding, no duplicates, an automated-production-use license scope
whose markets field is a JSON array of non-empty market strings covering both markets,
and `fallback=false`.

Provider payloads may contain additional symbols; those are `ALLOWED_NOT_SELECTED`.
Missing approved symbols, wrong markets, malformed license structures, stale/future
data, naive timestamps, normalization collisions, or any fallback fail closed.

This package performs zero network requests and accesses zero credentials. A PASS means
only that an already-authorized payload contract is technically qualifiable. It does not
change the Production source registry, resolve
`EXTERNAL_AUTHORIZED_INTRADAY_FEED_DEPENDENCY`, or grant scheduler, Decision State,
Portfolio, Ledger, CER-081 or Production acceptance credit.

A later provider-specific qualification and Control Center activation must bind the
actual provider contract/license, endpoint, credential handling, timestamp semantics and
registry entry before this validator can participate in Production.

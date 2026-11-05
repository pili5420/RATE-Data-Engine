# RATE Fugle Free/Basic Intraday Feasibility V1

Purpose: test whether Fugle's free/basic plan can technically satisfy RATE's
30-symbol 09:30/12:00 dual-market payload without changing Production authority.

## Approved universe

Runtime callers cannot select or replace the diagnostic universe. The CLI always reads
`docs/contracts/RATE_FUGLE_FREE_INTRADAY_UNIVERSE_BINDING_V1.json`, and that file is
only a mirror. Before any credential/network use, the diagnostic compares the mirror
against the authoritative RATE Production universe chain provided by
`src.authorized_intraday_feed.load_authoritative_universe_binding()`.

The required universe remains exactly 30 symbols: TWSE 25 + TPEx 5. A different
25+5 list, changed snapshot, source bundle hash, universe contract hash or universe
binding hash fails closed before any HTTP request.

## HTTP request budget

The live diagnostic uses a direct `HTTPSConnection` to the fixed host
`api.fugle.tw`. It performs one GET for each approved symbol and has no automatic
retry or provider/endpoint fallback.

- maximum actual HTTP requests per qualification: 30
- 401: invalid API key, fail closed
- 403: plan not authorized, fail closed
- 429: plan rate limit insufficient, fail closed
- any 3xx: redirect forbidden, fail closed
- redirects followed: 0
- redirect target request: 0
- API key is never forwarded to another host

Fugle provided written confirmation on 2026-11-04 that the described personal,
single-user, private, automated non-display analytical use is permitted on the Basic
user plan, and that approximately 30 requests per cadence is within the current
60-requests-per-minute Taiwan-equity intraday limit. This establishes the provider
plan/use-scope gate only.

## Exchange-authority boundary

Fugle explicitly did **not** provide TWSE or TPEx authorization on behalf of those
exchanges. RATE therefore keeps exchange authority as a separate fail-closed gate.

No Fugle provider confirmation may be interpreted as proof that TWSE/TPEx non-display
or data-feed permissions are satisfied. Production remains blocked until the existing
provider-authority contract receives Control-Center-approved TWSE and TPEx evidence
references and hashes covering the required real-time non-display/internal-use scope.

## Output custody

The CLI does not accept an arbitrary binding path or arbitrary output path.

Output is restricted to the fixed diagnostic root:

`artifacts/diagnostics/fugle-free-intraday`

The operator supplies only a JSON basename through `--output-name`. Path traversal,
absolute/nested paths, existing files and a symlinked output root fail before binding
or network qualification. Successful evidence is written with exclusive-create mode;
an existing path is never overwritten.

This prevents the diagnostic command from selecting or overwriting Production
artifacts.

## Qualification boundary

The provider-plan license gate is now `PASS_CONFIRMED_IN_WRITING`, bound to `RATE_FUGLE_BASIC_PERSONAL_INTERNAL_USE_LICENSE_EVIDENCE_V1`, but that does
not grant Production authority and does not resolve the external dependency.

- `production_eligible=false`
- `registry_activation_allowed=false`
- `external_dependency_resolved=false`
- `exchange_authority_gate=UNPROVEN`

No live request is run by PR CI. Any new live qualification requires a fresh explicit
Control Center authorization because the previous single-use permit was consumed by
the blocked 2026-11-04 run. Production registry, scheduler, Decision State, Portfolio, Ledger and CER-081 remain outside this diagnostic. Fugle is a qualified provider option only and is not activated in Route B; this evidence makes no Route B source-architecture change.

# RATE Fugle Free/Basic Intraday Feasibility V1

Purpose: test whether Fugle's free/basic trial can technically satisfy RATE's
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
- 403: free/basic plan not authorized, fail closed
- 429: free/basic rate limit insufficient, fail closed
- any 3xx: redirect forbidden, fail closed
- redirects followed: 0
- redirect target request: 0
- API key is never forwarded to another host

The request counter is incremented before each direct network attempt. A successful
30/30 diagnostic therefore corresponds to exactly 30 HTTP requests.

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

A technical PASS is **not** a license PASS. Until Fugle explicitly confirms that the
account/plan permits RATE's non-display automated analytical use, the result remains:

- `production_eligible=false`
- `registry_activation_allowed=false`
- `external_dependency_resolved=false`

No live request is run by PR CI. A later Owner-authorized manual probe must supply
`FUGLE_API_KEY` and execute near 09:30 or 12:00. Production registry, scheduler,
Decision State, Portfolio, Ledger and CER-081 remain outside this diagnostic.
